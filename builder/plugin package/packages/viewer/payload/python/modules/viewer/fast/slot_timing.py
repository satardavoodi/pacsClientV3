"""Slot-timing observability for FAST-viewer silent main-thread blocker triage (G6+).

This module provides a tiny, dependency-light instrumentation helper used to
attribute the residual ~500–600 ms drag-active main-thread stalls observed on
top of the F8 (`[MAIN_THREAD_STALL]`) and F11 (`[MAIN_THREAD_STALL_TRACE]`)
probes (see `docs/plans/performance/FAST_VIEWER_OPTIMIZATION_STATE_2026-04-29.md`).

Design constraints (per the optimization state doc § 9):

- Observation-only — never changes behavior of the wrapped function.
- Cheap on the fast path — `time.perf_counter()` × 2 + a single dict get + a
  threshold compare. Nothing is logged when the call is fast and we are not
  drag-active.
- Async log emit — uses the standard logging facility which is wired through
  `QueueHandler` (R7), so the emit is never the blocker we are trying to find.
- Drag-aware — every record includes `drag_active=<bool>` so the harness can
  separate "slow because drag is hot" from "slow because of intrinsic cost".
- Failure-safe — wrapped functions still run even if the timing helper raises.

Emit format (stable contract — keep in sync with the parser at
`tools/performance/clearcanvas_aipacs_kpi_harness.py::parse_slot_timing_log_text`):

    [SLOT_TIMING] tag=<TAG> duration_ms=<F.3> drag_active=<True|False>
                  threshold_ms=<F.1> series=<SN|none> extra=<k1=v1;k2=v2>

`tag` is a stable function identifier (e.g. `thumbnail.complete_series_download`).
`extra` is an optional semicolon-separated `k=v` block reserved for low-arity
qualifiers (series count, viewer count, etc.). Never put PHI in extra.

Environment variables:

- `AIPACS_SLOT_TIMING_TRACE`     — `1` (default) enables emission; `0` disables.
- `AIPACS_SLOT_TIMING_THRESHOLD_MS` — default 30.0; calls faster than this AND
                                    not drag-active produce no log line.
- `AIPACS_SLOT_TIMING_DRAG_THRESHOLD_MS` — default 8.0; under drag, anything
                                    longer than this emits (drag is delicate).

The helper is intentionally importable from non-viewer modules (it does not
itself depend on PySide6); it lazily imports `is_protected_drag_active` so a
broken import in `ui_throttle` cannot disable thumbnail/DM logging.
"""

from __future__ import annotations

import functools
import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Callable, Mapping, Optional

__all__ = [
    "slot_timing",
    "time_slot",
    "emit_slot_timing",
    "is_slot_timing_enabled",
    "current_slot_timing_thresholds",
]

_LOG = logging.getLogger("aipacs.viewer.slot_timing")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def is_slot_timing_enabled() -> bool:
    """Return True if `[SLOT_TIMING]` emission is enabled (default on)."""
    raw = os.environ.get("AIPACS_SLOT_TIMING_TRACE", "1")
    return raw not in ("0", "false", "False", "no", "NO")


def current_slot_timing_thresholds() -> tuple[float, float]:
    """Return ``(idle_threshold_ms, drag_threshold_ms)`` from env or defaults."""
    return (
        _env_float("AIPACS_SLOT_TIMING_THRESHOLD_MS", 30.0),
        _env_float("AIPACS_SLOT_TIMING_DRAG_THRESHOLD_MS", 8.0),
    )


def _resolve_drag_active() -> bool:
    """Best-effort `is_protected_drag_active()` probe.

    Lazy import + try/except so this helper can be used from modules that
    are loaded before / outside the viewer package (thumbnail_manager,
    home_download_service, etc.).
    """
    try:
        from modules.viewer.fast.ui_throttle import is_protected_drag_active

        return bool(is_protected_drag_active())
    except Exception:
        return False


def _format_extra(extra: Optional[Mapping[str, Any]]) -> str:
    if not extra:
        return ""
    parts: list[str] = []
    for key, value in extra.items():
        try:
            sval = str(value)
        except Exception:
            sval = "<unrepr>"
        # Strip whitespace and the field separators we use.
        sval = sval.replace(";", ",").replace("=", ":").strip()
        parts.append(f"{key}={sval}")
    return ";".join(parts)


def emit_slot_timing(
    tag: str,
    duration_ms: float,
    *,
    drag_active: Optional[bool] = None,
    series: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
    force: bool = False,
) -> bool:
    """Emit one `[SLOT_TIMING]` line if duration crosses the threshold.

    Returns True if the line was emitted. Safe to call directly from a
    `try/finally` block when the @slot_timing decorator does not fit.

    `force=True` bypasses the threshold (use for sentinel emits like begin/end
    markers around bursts).
    """
    if not is_slot_timing_enabled():
        return False

    if drag_active is None:
        drag_active = _resolve_drag_active()

    idle_thr, drag_thr = current_slot_timing_thresholds()
    threshold_ms = drag_thr if drag_active else idle_thr

    if not force and duration_ms < threshold_ms:
        return False

    extra_str = _format_extra(extra)
    series_field = series if series else "none"

    try:
        _LOG.info(
            "[SLOT_TIMING] tag=%s duration_ms=%.3f drag_active=%s "
            "threshold_ms=%.1f series=%s extra=%s",
            tag,
            float(duration_ms),
            bool(drag_active),
            threshold_ms,
            series_field,
            extra_str,
            extra={"component": "viewer"},
        )
        return True
    except Exception:
        # Never let observability break the wrapped function.
        return False


def slot_timing(
    tag: str,
    *,
    series_arg: Optional[str] = None,
    extra_factory: Optional[Callable[..., Mapping[str, Any]]] = None,
):
    """Decorator that emits `[SLOT_TIMING]` for every call of the wrapped fn.

    Parameters
    ----------
    tag
        Stable identifier (e.g. ``"thumbnail.complete_series_download"``).
    series_arg
        Optional name of the keyword/positional argument carrying the series
        number (used for ``series=`` field). Resolution rules: kwarg by name
        first; otherwise positional ``[1]`` if available (skipping ``self``).
    extra_factory
        Optional callable invoked as ``extra_factory(*args, **kwargs)`` after
        the wrapped function returns. Must be cheap and exception-safe — any
        raise is swallowed and `extra` is dropped.
    """

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            if not is_slot_timing_enabled():
                return func(*args, **kwargs)
            t0 = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                try:
                    duration_ms = (time.perf_counter() - t0) * 1000.0
                    series_value: Optional[str] = None
                    if series_arg is not None:
                        if series_arg in kwargs:
                            series_value = str(kwargs[series_arg])
                        elif len(args) >= 2:
                            series_value = str(args[1])
                    extra_payload: Optional[Mapping[str, Any]] = None
                    if extra_factory is not None:
                        try:
                            extra_payload = extra_factory(*args, **kwargs)
                        except Exception:
                            extra_payload = None
                    emit_slot_timing(
                        tag,
                        duration_ms,
                        series=series_value,
                        extra=extra_payload,
                    )
                except Exception:
                    pass

        return _wrapped

    return _decorator


@contextmanager
def time_slot(
    tag: str,
    *,
    series: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
    force: bool = False,
):
    """Context manager variant for inline blocks.

    Usage::

        with time_slot("home_download.on_series_completed", series=str(sn)):
            ...
    """
    if not is_slot_timing_enabled():
        yield
        return

    t0 = time.perf_counter()
    try:
        yield
    finally:
        try:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            emit_slot_timing(
                tag,
                duration_ms,
                series=series,
                extra=extra,
                force=force,
            )
        except Exception:
            pass
