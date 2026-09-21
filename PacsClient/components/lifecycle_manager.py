"""Centralised resource-lifecycle manager for AIPacs.

Every subsystem that owns a thread-pool, daemon thread, cache, subprocess,
or open connection registers a shutdown callback here.  At application
close `LifecycleManager.shutdown_all()` invokes them in reverse-registration
order (LIFO) so dependees are released before dependencies.
Callbacks run synchronously on the caller's thread. An asynchronous stop callback
does not imply its workers have drained; timeouts are post-return diagnostics,
not enforced deadlines. Callers must not register GUI-blocking waits here.

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
        self._completion_probes: Dict[str, Callable[[], Optional[bool]]] = {}
        self._last_shutdown: List[dict] = []
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
            Advisory duration budget, checked only after the callback returns.
            Does not interrupt a callback or enforce a deadline.
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
        """Remove all entries with *name*, including its completion probe."""
        with self._lock:
            self._resources = [
                (n, cb, t) for n, cb, t in self._resources if n != name
            ]
            self._health_checks.pop(name, None)
            self._completion_probes.pop(name, None)

    def register_completion_probe(
        self, name: str, probe: Callable[[], Optional[bool]],
    ) -> None:
        """Attach a read-only, nonblocking owner-state probe to a resource name.

        Sampled once after its callback, on the shutdown caller's thread. True
        confirms completion, False means pending, None means unknown. No waits,
        I/O, event pumping, or Qt construction are allowed in probes. The manager
        retains only primitive observations after shutdown, not owner closures.
        """
        with self._lock:
            if self._shutting_down:
                return
            self._completion_probes[name] = probe

    def last_shutdown_snapshot(self) -> List[dict]:
        """Return copies of observations at callback return, not a live drain gate."""
        with self._lock:
            return [dict(record) for record in self._last_shutdown]

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def shutdown_all(self) -> Dict[str, Optional[str]]:
        """Invoke every registered callback synchronously in LIFO order.

        Returns a dict mapping resource name → ``None`` (success) or an
        error string. Success means callback return, not asynchronous completion.
        Errors are logged but never propagated — the
        shutdown sequence is never aborted by a single failure.
        """
        with self._lock:
            if self._shutting_down:
                log.info("[LIFECYCLE_SHUTDOWN] phase=reentrant_call_ignored")
                return {}
            self._shutting_down = True
            snapshot = list(reversed(self._resources))
            self._resources.clear()
            self._health_checks.clear()
            probes = dict(self._completion_probes)
            self._completion_probes.clear()
            self._last_shutdown = []

        results: Dict[str, Optional[str]] = {}
        observations = []
        try:
            for ordinal, (name, callback, timeout) in enumerate(snapshot, 1):
                log.info("[LIFECYCLE_SHUTDOWN] phase=callback_begin ordinal=%s owner=%s",
                         ordinal, name)
                t0 = time.monotonic()
                outcome = "returned"
                try:
                    callback()
                    elapsed = time.monotonic() - t0
                    if elapsed > timeout:
                        outcome = "over_budget"
                        msg = f"completed but exceeded timeout ({elapsed:.1f}s > {timeout:.1f}s)"
                        log.warning("shutdown(%s): %s", name, msg)
                        results[name] = msg
                    else:
                        results[name] = None
                except Exception as exc:
                    elapsed = time.monotonic() - t0
                    outcome = "error"
                    log.warning("shutdown(%s): error – %s", name, exc)
                    results[name] = str(exc)
                log.info(
                    "[LIFECYCLE_SHUTDOWN] phase=callback_return ordinal=%s owner=%s "
                    "outcome=%s elapsed_ms=%.2f", ordinal, name, outcome, elapsed * 1000,
                )
                completion = "unknown"
                probe_ms = 0.0
                probe = probes.get(name)
                if probe is not None:
                    p0 = time.monotonic()
                    try:
                        answer = probe()
                        if answer is True:
                            completion = "complete"
                        elif answer is False:
                            completion = "pending"
                    except Exception:
                        completion = "probe_error"
                    probe_ms = (time.monotonic() - p0) * 1000
                observations.append({
                    "ordinal": ordinal, "name": name, "callback_outcome": outcome,
                    "callback_ms": elapsed * 1000, "owner_completion": completion,
                    "probe_ms": probe_ms,
                })
                log.info(
                    "[LIFECYCLE_SHUTDOWN] phase=owner_observation ordinal=%s owner=%s "
                    "owner_completion=%s probe_ms=%.2f", ordinal, name, completion, probe_ms,
                )
        finally:
            with self._lock:
                self._last_shutdown = observations
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
