"""Centralised resource-lifecycle manager for AIPacs.

Every subsystem that owns a thread-pool, daemon thread, cache, subprocess,
or open connection registers a shutdown callback here.  At application
close `LifecycleManager.shutdown_all()` drains them in reverse-registration
order (LIFO) so dependees are released before dependencies.

Usage
-----
    from PacsClient.components.lifecycle_manager import lifecycle_manager

    # In component setup:
    lifecycle_manager.register("MyWidget.thread_pool", pool.shutdown)

    # In MainWindow.closeEvent:
    lifecycle_manager.shutdown_all()

The manager also acts as a lightweight **health monitor**.  Components can
register periodic health-check callables; call `health_snapshot()` at any
time to collect a dict of component → ok/error.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


class LifecycleManager:
    """Singleton-like registry of shutdown callbacks & optional health checks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # (name, callback, timeout_s)
        self._resources: List[Tuple[str, Callable[[], None], float]] = []
        # name → health_check_callable (returns True if healthy)
        self._health_checks: Dict[str, Callable[[], bool]] = {}
        self._shutting_down = False

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(
        self,
        name: str,
        shutdown_cb: Callable[[], None],
        timeout: float = 5.0,
    ) -> None:
        """Register *shutdown_cb* to be called during ``shutdown_all()``.

        Parameters
        ----------
        name:
            Human-readable label (e.g. ``"HomePanelWidget.thread_pool"``).
        shutdown_cb:
            Zero-arg callable that releases the resource.  Must be safe to
            call more than once (idempotent).
        timeout:
            Max seconds to wait for the callback before moving on.
        """
        with self._lock:
            if self._shutting_down:
                log.warning("register(%s) called during shutdown – ignored", name)
                return
            self._resources.append((name, shutdown_cb, timeout))
            log.debug("Registered resource: %s (timeout=%.1fs)", name, timeout)

    def register_health_check(
        self,
        name: str,
        check: Callable[[], bool],
    ) -> None:
        """Register a health-check callable for *name*."""
        with self._lock:
            self._health_checks[name] = check

    def unregister(self, name: str) -> None:
        """Remove all entries with *name* (resource + health check)."""
        with self._lock:
            self._resources = [
                (n, cb, t) for n, cb, t in self._resources if n != name
            ]
            self._health_checks.pop(name, None)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def shutdown_all(self) -> Dict[str, Optional[str]]:
        """Drain every registered resource in LIFO order.

        Returns a dict mapping resource name → ``None`` (success) or an
        error string.  Errors are logged but never propagated — the
        shutdown sequence is never aborted by a single failure.
        """
        with self._lock:
            self._shutting_down = True
            snapshot = list(reversed(self._resources))
            self._resources.clear()
            self._health_checks.clear()

        results: Dict[str, Optional[str]] = {}
        for name, callback, timeout in snapshot:
            t0 = time.monotonic()
            try:
                callback()
                elapsed = time.monotonic() - t0
                if elapsed > timeout:
                    msg = f"completed but exceeded timeout ({elapsed:.1f}s > {timeout:.1f}s)"
                    log.warning("shutdown(%s): %s", name, msg)
                    results[name] = msg
                else:
                    log.debug("shutdown(%s): ok (%.2fs)", name, elapsed)
                    results[name] = None
            except Exception as exc:
                log.warning("shutdown(%s): error – %s", name, exc)
                results[name] = str(exc)

        with self._lock:
            self._shutting_down = False
        return results

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def health_snapshot(self) -> Dict[str, bool]:
        """Run all registered health checks and return name → healthy."""
        with self._lock:
            checks = dict(self._health_checks)
        out: Dict[str, bool] = {}
        for name, fn in checks.items():
            try:
                out[name] = fn()
            except Exception:
                out[name] = False
        return out

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def resource_count(self) -> int:
        with self._lock:
            return len(self._resources)

    @property
    def is_shutting_down(self) -> bool:
        with self._lock:
            return self._shutting_down

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"<LifecycleManager resources={len(self._resources)} "
                f"health_checks={len(self._health_checks)} "
                f"shutting_down={self._shutting_down}>"
            )


# Module-level singleton
lifecycle_manager = LifecycleManager()
