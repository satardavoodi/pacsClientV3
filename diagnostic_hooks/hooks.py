"""
diagnostic_hooks/hooks.py
==========================
Individual hook definitions for FAST viewer diagnostics.

All hooks are gated by ``AIPACS_DIAG_MODE=1``.  The module must not be
imported unless that variable is set — HookManager handles the gate.

Each hook is a callable that wraps one production method with a spy closure
that records events into the shared EventLog without altering behaviour.

Hook catalogue (13 hooks)
--------------------------
H-01  _start_progressive_display
H-02  _grow_progressive_fast
H-03  _refresh_stored_metadata_instances
H-04  on_series_images_progress
H-05  on_series_download_fully_complete
H-06  _completion_verify_series
H-07  _completion_sweep_tick
H-08  _bind_backend_from_metadata
H-09  _activate_progressive_mode_on_viewers
H-10  PyDicomLazyVolume.grow
H-11  PyDicomLazyVolume.request_slice_loaded
H-12  lazy_volume_registry.register_loader
H-13  lazy_volume_registry.release_loader
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Optional

# All EventLog imports are local so this module can be safely imported
# without requiring tests.diagnostics in the production path.
# HookManager will only call install_all() when AIPACS_DIAG_MODE=1.


def _make_spy_wrapper(
    original: Callable,
    log_append_fn: Callable,
    event_begin: str,
    event_end: str,
    *,
    extract_args: Optional[Callable] = None,
) -> Callable:
    """Generic timing wrapper: logs begin/end events around the original call."""

    def _wrapped(*args, **kwargs):
        fields = {}
        if extract_args is not None:
            try:
                fields = extract_args(args, kwargs)
            except Exception:
                pass
        log_append_fn(event_begin, **fields)
        t0 = time.perf_counter()
        try:
            result = original(*args, **kwargs)
            return result
        except Exception as exc:
            from tests.diagnostics.event_log import ET_EXCEPTION_SWALLOWED
            log_append_fn(ET_EXCEPTION_SWALLOWED, hook=event_begin, exc=repr(exc))
            raise
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            log_append_fn(event_end, elapsed_ms=elapsed_ms, **fields)

    _wrapped.__wrapped__ = original  # allow detach
    return _wrapped


# ─── Hook installers ──────────────────────────────────────────────────────────

def hook_start_progressive_display(controller: Any, log_append_fn: Callable) -> None:
    """H-01: wrap _start_progressive_display."""
    from tests.diagnostics.event_log import ET_PROGRESSIVE_START, ET_INFLIGHT_SET

    original = getattr(controller, "_start_progressive_display", None)
    if original is None or hasattr(original, "__wrapped__"):
        return

    def _extract(args, kwargs):
        # _start_progressive_display(self, series_number, downloaded, total)
        if len(args) >= 2:
            return {"series_number": str(args[1])}
        return {}

    def _wrapped(*args, **kwargs):
        fields = _extract(args, kwargs)
        log_append_fn(ET_INFLIGHT_SET, **fields)
        log_append_fn(ET_PROGRESSIVE_START, **fields)
        t0 = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            log_append_fn(ET_PROGRESSIVE_START + "_DONE", elapsed_ms=elapsed_ms, **fields)

    _wrapped.__wrapped__ = original
    controller._start_progressive_display = _wrapped


def hook_grow_progressive_fast(controller: Any, log_append_fn: Callable) -> None:
    """H-02: wrap _grow_progressive_fast."""
    from tests.diagnostics.event_log import (
        ET_PROGRESSIVE_GROW,
        ET_PROGRESSIVE_STALE,
        ET_EXCEPTION_SWALLOWED,
    )

    original = getattr(controller, "_grow_progressive_fast", None)
    if original is None or hasattr(original, "__wrapped__"):
        return

    def _extract(args, kwargs):
        if len(args) >= 2:
            return {"series_number": str(args[1])}
        return {}

    def _wrapped(*args, **kwargs):
        fields = _extract(args, kwargs)
        log_append_fn(ET_PROGRESSIVE_GROW, **fields)
        t0 = time.perf_counter()
        try:
            result = original(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            log_append_fn(
                ET_PROGRESSIVE_GROW + "_DONE",
                elapsed_ms=elapsed_ms,
                result=repr(result),
                **fields,
            )
            return result
        except Exception as exc:
            log_append_fn(ET_EXCEPTION_SWALLOWED, hook="grow_progressive_fast", exc=repr(exc))
            raise

    _wrapped.__wrapped__ = original
    controller._grow_progressive_fast = _wrapped


def hook_refresh_metadata(controller: Any, log_append_fn: Callable) -> None:
    """H-03: wrap _refresh_stored_metadata_instances (primary H1 probe)."""
    from tests.diagnostics.event_log import (
        ET_METADATA_REFRESH_BEGIN,
        ET_METADATA_REFRESH_DONE,
    )

    original = getattr(controller, "_refresh_stored_metadata_instances", None)
    if original is None or hasattr(original, "__wrapped__"):
        return

    def _extract(args, kwargs):
        if len(args) >= 2:
            return {"series_number": str(args[1])}
        return {}

    def _wrapped(*args, **kwargs):
        fields = _extract(args, kwargs)
        log_append_fn(ET_METADATA_REFRESH_BEGIN, **fields)
        t0 = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            log_append_fn(ET_METADATA_REFRESH_DONE, elapsed_ms=elapsed_ms, **fields)

    _wrapped.__wrapped__ = original
    controller._refresh_stored_metadata_instances = _wrapped


def hook_on_series_images_progress(controller: Any, log_append_fn: Callable) -> None:
    """H-04: wrap on_series_images_progress."""
    from tests.diagnostics.event_log import ET_SERIES_PROGRESS

    original = getattr(controller, "on_series_images_progress", None)
    if original is None or hasattr(original, "__wrapped__"):
        return

    def _wrapped(series_number, downloaded, total):
        log_append_fn(
            ET_SERIES_PROGRESS,
            series_number=str(series_number),
            downloaded=downloaded,
            total=total,
        )
        return original(series_number, downloaded, total)

    _wrapped.__wrapped__ = original
    controller.on_series_images_progress = _wrapped


def hook_download_fully_complete(controller: Any, log_append_fn: Callable) -> None:
    """H-05: wrap on_series_download_fully_complete."""
    from tests.diagnostics.event_log import ET_SERIES_DOWNLOAD_COMPLETE, ET_INFLIGHT_CLEARED

    original = getattr(controller, "on_series_download_fully_complete", None)
    if original is None or hasattr(original, "__wrapped__"):
        return

    def _wrapped(series_number, *args, **kwargs):
        log_append_fn(ET_SERIES_DOWNLOAD_COMPLETE, series_number=str(series_number))
        try:
            return original(series_number, *args, **kwargs)
        finally:
            log_append_fn(ET_INFLIGHT_CLEARED, series_number=str(series_number))

    _wrapped.__wrapped__ = original
    controller.on_series_download_fully_complete = _wrapped


def hook_completion_verify(controller: Any, log_append_fn: Callable) -> None:
    """H-06: wrap _completion_verify_series."""
    from tests.diagnostics.event_log import (
        ET_COMPLETION_VERIFY_START,
        ET_COMPLETION_VERIFY_DONE,
    )

    original = getattr(controller, "_completion_verify_series", None)
    if original is None or hasattr(original, "__wrapped__"):
        return

    def _extract(args, kwargs):
        if len(args) >= 2:
            return {"series_number": str(args[1])}
        return {}

    wrapped = _make_spy_wrapper(
        original,
        log_append_fn,
        ET_COMPLETION_VERIFY_START,
        ET_COMPLETION_VERIFY_DONE,
        extract_args=_extract,
    )
    controller._completion_verify_series = wrapped


def hook_completion_sweep(controller: Any, log_append_fn: Callable) -> None:
    """H-07: wrap _completion_sweep_tick."""
    from tests.diagnostics.event_log import ET_COMPLETION_SWEEP_TICK

    original = getattr(controller, "_completion_sweep_tick", None)
    if original is None or hasattr(original, "__wrapped__"):
        return

    def _wrapped(*args, **kwargs):
        log_append_fn(ET_COMPLETION_SWEEP_TICK)
        return original(*args, **kwargs)

    _wrapped.__wrapped__ = original
    controller._completion_sweep_tick = _wrapped


def hook_bind_backend(controller: Any, log_append_fn: Callable) -> None:
    """H-08: wrap _bind_backend_from_metadata."""
    from tests.diagnostics.event_log import ET_BACKEND_BIND

    original = getattr(controller, "_bind_backend_from_metadata", None)
    if original is None or hasattr(original, "__wrapped__"):
        return

    def _extract(args, kwargs):
        if len(args) >= 2:
            return {"series_number": str(args[1])}
        return {}

    def _wrapped(*args, **kwargs):
        fields = _extract(args, kwargs)
        log_append_fn(ET_BACKEND_BIND, **fields)
        return original(*args, **kwargs)

    _wrapped.__wrapped__ = original
    controller._bind_backend_from_metadata = _wrapped


def hook_lazy_volume_grow(loader: Any, log_append_fn: Callable) -> None:
    """H-10: wrap PyDicomLazyVolume.grow."""
    from tests.diagnostics.event_log import ET_GROW_CALLED, ET_GROW_RETURNED

    original = getattr(loader, "grow", None)
    if original is None or hasattr(original, "__wrapped__"):
        return

    def _wrapped(*args, **kwargs):
        log_append_fn(ET_GROW_CALLED)
        t0 = time.perf_counter()
        try:
            result = original(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            log_append_fn(ET_GROW_RETURNED, elapsed_ms=elapsed_ms, result=repr(result))
            return result
        except Exception as exc:
            from tests.diagnostics.event_log import ET_EXCEPTION_SWALLOWED
            log_append_fn(ET_EXCEPTION_SWALLOWED, hook="grow", exc=repr(exc))
            raise

    _wrapped.__wrapped__ = original
    loader.grow = _wrapped


def hook_loader_registry(log_append_fn: Callable) -> None:
    """H-12/H-13: wrap lazy_volume_registry register/release."""
    from tests.diagnostics.event_log import ET_LOADER_CREATED, ET_LOADER_RELEASED

    try:
        import modules.viewer.fast.lazy_volume_registry as reg
    except ImportError:
        return

    # register_loader
    orig_register = getattr(reg, "register_loader", None)
    if orig_register and not hasattr(orig_register, "__wrapped__"):
        def _reg_wrapped(key, loader):
            log_append_fn(ET_LOADER_CREATED, registry_key=str(key))
            return orig_register(key, loader)
        _reg_wrapped.__wrapped__ = orig_register
        reg.register_loader = _reg_wrapped

    # release_loader
    orig_release = getattr(reg, "release_loader", None)
    if orig_release and not hasattr(orig_release, "__wrapped__"):
        def _rel_wrapped(key):
            log_append_fn(ET_LOADER_RELEASED, registry_key=str(key))
            return orig_release(key)
        _rel_wrapped.__wrapped__ = orig_release
        reg.release_loader = _rel_wrapped


# ─── install_all / remove_all ─────────────────────────────────────────────────

def install_all(controller: Any, log_append_fn: Callable) -> None:
    """Install all 13 hooks on the given controller.

    Safe to call more than once — idempotent (checks ``__wrapped__``).
    """
    hook_start_progressive_display(controller, log_append_fn)
    hook_grow_progressive_fast(controller, log_append_fn)
    hook_refresh_metadata(controller, log_append_fn)
    hook_on_series_images_progress(controller, log_append_fn)
    hook_download_fully_complete(controller, log_append_fn)
    hook_completion_verify(controller, log_append_fn)
    hook_completion_sweep(controller, log_append_fn)
    hook_bind_backend(controller, log_append_fn)
    hook_loader_registry(log_append_fn)


def remove_all(controller: Any) -> None:
    """Remove all diagnostic hooks and restore originals."""
    _HOOKED_METHODS = [
        "_start_progressive_display",
        "_grow_progressive_fast",
        "_refresh_stored_metadata_instances",
        "on_series_images_progress",
        "on_series_download_fully_complete",
        "_completion_verify_series",
        "_completion_sweep_tick",
        "_bind_backend_from_metadata",
    ]
    for name in _HOOKED_METHODS:
        wrapped = getattr(controller, name, None)
        if wrapped is not None and hasattr(wrapped, "__wrapped__"):
            setattr(controller, name, wrapped.__wrapped__)
