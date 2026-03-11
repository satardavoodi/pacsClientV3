"""Circuit-breaker for network endpoints (socket, gRPC, HTTP).

Prevents cascading failures by short-circuiting calls to an endpoint
that has failed repeatedly.  Three states:

    CLOSED  → calls pass through normally; failures increment a counter.
    OPEN    → calls are immediately rejected; a cooldown timer runs.
    HALF_OPEN → one probe call is allowed; success resets, failure re-opens.

Usage
-----
    from PacsClient.pacs.patient_tab.utils.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("pacs-grpc", failure_threshold=5, cooldown=30.0)

    # Wrapping a call:
    try:
        result = cb.call(grpc_stub.GetStudy, request)
    except CircuitOpenError:
        show_offline_banner()

    # As a decorator:
    @cb.protect
    def fetch_study(uid):
        return grpc_stub.GetStudy(uid)
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from enum import Enum
from typing import Any, Callable, Optional, Tuple, Type, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is OPEN."""

    def __init__(self, name: str, remaining: float) -> None:
        self.name = name
        self.remaining = remaining
        super().__init__(
            f"Circuit '{name}' is OPEN — retry in {remaining:.1f}s"
        )


class CircuitBreaker:
    """Thread-safe circuit breaker for a single named endpoint."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown: float = 30.0,
        success_threshold: int = 2,
        tracked_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self.success_threshold = success_threshold
        self.tracked_exceptions = tracked_exceptions

        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute *fn* through the breaker.  Raises ``CircuitOpenError``
        if the circuit is OPEN and the cooldown has not elapsed."""
        self._before_call()
        try:
            result = fn(*args, **kwargs)
        except self.tracked_exceptions as exc:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result

    def protect(self, fn: Callable[..., T]) -> Callable[..., T]:
        """Decorator form of :meth:`call`."""

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return self.call(fn, *args, **kwargs)

        return wrapper

    def reset(self) -> None:
        """Manually force the breaker back to CLOSED."""
        with self._lock:
            old = self._state
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            if old != CircuitState.CLOSED:
                self._fire_change(old, CircuitState.CLOSED)

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def on_state_change(
        self, cb: Callable[[CircuitState, CircuitState], None]
    ) -> None:
        """Register a listener called with (old_state, new_state)."""
        self._on_state_change = cb

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _before_call(self) -> None:
        with self._lock:
            if self._state is CircuitState.CLOSED:
                return
            if self._state is CircuitState.HALF_OPEN:
                return  # allow probe
            # OPEN — check cooldown
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.cooldown:
                old = self._state
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                log.info("CircuitBreaker(%s): OPEN → HALF_OPEN after %.1fs cooldown", self.name, elapsed)
                self._fire_change(old, CircuitState.HALF_OPEN)
                return
            raise CircuitOpenError(self.name, self.cooldown - elapsed)

    def _on_success(self) -> None:
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    old = self._state
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    log.info("CircuitBreaker(%s): HALF_OPEN → CLOSED", self.name)
                    self._fire_change(old, CircuitState.CLOSED)
            elif self._state is CircuitState.CLOSED:
                # Successful call in closed state resets failure counter
                self._failure_count = 0

    def _on_failure(self) -> None:
        with self._lock:
            self._last_failure_time = time.monotonic()
            if self._state is CircuitState.HALF_OPEN:
                old = self._state
                self._state = CircuitState.OPEN
                log.warning("CircuitBreaker(%s): HALF_OPEN → OPEN (probe failed)", self.name)
                self._fire_change(old, CircuitState.OPEN)
            elif self._state is CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    old = self._state
                    self._state = CircuitState.OPEN
                    log.warning(
                        "CircuitBreaker(%s): CLOSED → OPEN after %d failures",
                        self.name,
                        self._failure_count,
                    )
                    self._fire_change(old, CircuitState.OPEN)

    def _fire_change(self, old: CircuitState, new: CircuitState) -> None:
        cb = self._on_state_change
        if cb is not None:
            try:
                cb(old, new)
            except Exception:
                log.debug("CircuitBreaker(%s): state_change callback error", self.name, exc_info=True)

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"<CircuitBreaker('{self.name}') state={self._state.value} "
                f"failures={self._failure_count}/{self.failure_threshold}>"
            )
