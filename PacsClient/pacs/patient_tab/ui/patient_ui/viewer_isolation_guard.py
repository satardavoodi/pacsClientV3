"""ViewerIsolationGuard — Centralized Mode B scroll-protection policy.

v2.2.3.6.0: This module provides a **single point of truth** for whether
the viewer is in an active scroll burst and therefore no heavy work should
run on the Qt main thread.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Callable

logger = logging.getLogger(__name__)


class ViewerIsolationGuard:
    """Per-widget guard that centralizes scroll-active state."""

    __slots__ = (
        '_scroll_active',
        '_scroll_start_ms',
        '_scroll_end_ms',
        '_deferred_work',
        '_mode_b_active',
        '_violation_count',
        '_last_violation_log_ms',
    )

    def __init__(self) -> None:
        self._scroll_active: bool = False
        self._scroll_start_ms: float = 0.0
        self._scroll_end_ms: float = 0.0
        self._deferred_work: deque = deque(maxlen=64)
        self._mode_b_active: bool = False
        self._violation_count: int = 0
        self._last_violation_log_ms: float = 0.0

    def enter_scroll(self) -> None:
        self._scroll_active = True
        self._scroll_start_ms = time.perf_counter() * 1000.0

    def exit_scroll(self) -> None:
        self._scroll_active = False
        self._scroll_end_ms = time.perf_counter() * 1000.0
        self._drain_deferred()

    def set_mode_b(self, active: bool) -> None:
        self._mode_b_active = active

    @property
    def is_scroll_active(self) -> bool:
        return self._scroll_active

    @property
    def is_mode_b(self) -> bool:
        return self._mode_b_active

    @property
    def scroll_idle_ms(self) -> float:
        if self._scroll_active:
            return 0.0
        return max(0.0, time.perf_counter() * 1000.0 - self._scroll_end_ms)

    def defer_if_scrolling(self, callback: Callable[[], None], label: str = "") -> bool:
        if not self._scroll_active:
            return False
        self._deferred_work.append((callback, label))
        logger.debug("[IsolationGuard] deferred '%s' (%d queued)", label, len(self._deferred_work))
        return True

    def _drain_deferred(self) -> None:
        drained = 0
        while self._deferred_work:
            cb, label = self._deferred_work.popleft()
            try:
                cb()
                drained += 1
            except Exception as e:
                logger.warning("[IsolationGuard] deferred '%s' failed: %s", label, e)
        if drained:
            logger.info("[IsolationGuard] drained %d deferred callbacks", drained)

    def check_no_heavy_work(self, caller: str, threshold_ms: float = 2.0) -> None:
        if not self._scroll_active:
            return
        self._violation_count += 1
        now_ms = time.perf_counter() * 1000.0
        if now_ms - self._last_violation_log_ms > 1000.0:
            self._last_violation_log_ms = now_ms
            logger.warning(
                "[IsolationGuard] VIOLATION #%d: '%s' ran during active scroll (total violations=%d)",
                self._violation_count,
                caller,
                self._violation_count,
            )

    @property
    def violation_count(self) -> int:
        return self._violation_count

    def reset_violations(self) -> None:
        self._violation_count = 0
