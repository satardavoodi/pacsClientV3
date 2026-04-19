"""Small shared throttling helpers for FAST viewer UI protection.

This module serves as the single facade for all load-aware policy queries
in the FAST viewer pipeline.  It bridges:
  - SystemLoadController (interaction state, UI lag, policy decisions)
  - ZetaBoost globals (_GLOBAL_DOWNLOAD_ACTIVE flag)
  - PipelineOrchestrator (per-tab download session state) — optional

Callers should use this module's public functions rather than querying
these subsystems directly.
"""

from __future__ import annotations

import threading
import time
from typing import Hashable, Optional

from modules.viewer.fast.block_telemetry import LiveBlockTelemetry
from modules.viewer.fast.system_load_controller import get_system_load_controller
from modules.viewer.fast.system_load_controller import BlockId
from modules.viewer.fast.system_load_controller import WorkClass


_LOCK = threading.Lock()
_LAST_EVENT_MS: dict[Hashable, float] = {}

# Optional per-tab orchestrator for download-session queries.
# Set by ViewerController on tab init; cleared on teardown.
_ACTIVE_ORCHESTRATOR: Optional[object] = None
_ORCHESTRATOR_LOCK = threading.Lock()
_ACTIVE_BLOCK_TELEMETRY: Optional[LiveBlockTelemetry] = None


def set_active_orchestrator(orch) -> None:
    """Register the active PipelineOrchestrator for download queries."""
    global _ACTIVE_ORCHESTRATOR, _ACTIVE_BLOCK_TELEMETRY
    with _ORCHESTRATOR_LOCK:
        _ACTIVE_ORCHESTRATOR = orch
        _ACTIVE_BLOCK_TELEMETRY = LiveBlockTelemetry(orchestrator=orch)


def clear_active_orchestrator(orch=None) -> None:
    """Unregister the active orchestrator (idempotent)."""
    global _ACTIVE_ORCHESTRATOR, _ACTIVE_BLOCK_TELEMETRY
    with _ORCHESTRATOR_LOCK:
        if orch is None or _ACTIVE_ORCHESTRATOR is orch:
            _ACTIVE_ORCHESTRATOR = None
            _ACTIVE_BLOCK_TELEMETRY = None


def _now_ms() -> float:
    return time.monotonic() * 1000.0


def record_fast_interaction(active: bool, *, grace_ms: float = 250.0) -> None:
    """Record whether the viewer is actively scrolling/dragging."""
    get_system_load_controller().update_fast_interaction(active, grace_ms=grace_ms)


def is_fast_interaction_active() -> bool:
    return get_system_load_controller().is_fast_interaction_active()


def is_heavy_download_active(*, grace_ms: float = 750.0) -> bool:
    """Return download activity with a short grace window after bursts.

    Probes two independent sources:
      1. ZetaBoost globals (_GLOBAL_DOWNLOAD_ACTIVE flag)
      2. PipelineOrchestrator (per-tab download session state) — if registered

    Returns True if EITHER source reports active downloads.
    """
    active = False
    try:
        from modules.zeta_boost.cache_engine import _zb_globals

        helper = getattr(_zb_globals, "is_heavy_download_active", None)
        if callable(helper):
            active = bool(helper(grace_ms=grace_ms))
        else:
            active = bool(getattr(_zb_globals, "_GLOBAL_DOWNLOAD_ACTIVE", False))
    except Exception:
        pass

    if not active:
        with _ORCHESTRATOR_LOCK:
            orch = _ACTIVE_ORCHESTRATOR
        if orch is not None:
            try:
                active = bool(orch.is_heavy_download_active())
            except Exception:
                pass

    return active


def should_defer_noncritical_open_network(*, first_series_visible: bool) -> bool:
    """Return True when cosmetic open-path network work should yield.

    Policy: while heavy download overlap is active, non-essential network work
    such as remote thumbnail refresh or attachment fetch should wait until the
    first clinically useful image is visible.
    """
    return bool(is_heavy_download_active() and not bool(first_series_visible))


def record_ui_heartbeat(*, nominal_interval_ms: float = 16.0) -> float:
    """Record a UI-thread callback tick and return the current lag estimate."""
    return get_system_load_controller().record_ui_tick(
        nominal_interval_ms=nominal_interval_ms,
    )


def get_ui_event_loop_lag_ms() -> float:
    """Return the freshest UI lag estimate, or 0 when stale/unknown."""
    return get_system_load_controller().get_ui_event_loop_lag_ms()


def progressive_signal_interval_ms() -> float:
    return get_system_load_controller().progressive_signal_interval_ms(
        heavy_download_active=is_heavy_download_active(),
    )


def progress_update_interval_ms() -> float:
    return get_system_load_controller().progress_update_interval_ms(
        heavy_download_active=is_heavy_download_active(),
    )


def progressive_grow_interval_ms() -> float:
    return get_system_load_controller().progressive_grow_interval_ms(
        heavy_download_active=is_heavy_download_active(),
        fast_interaction_active=is_fast_interaction_active(),
    )


def thumbnail_progress_interval_ms() -> float:
    return get_system_load_controller().thumbnail_progress_interval_ms(
        heavy_download_active=is_heavy_download_active(),
    )


def thumbnail_log_interval_ms() -> float:
    return get_system_load_controller().thumbnail_log_interval_ms(
        heavy_download_active=is_heavy_download_active(),
    )


def should_defer_progressive_grow(*, terminal: bool = False) -> bool:
    """Return True when non-terminal grow work should yield to protected UI."""
    return not get_system_load_controller().should_admit(
        WorkClass.PROGRESSIVE_GROW,
        {"terminal": bool(terminal)},
        heavy_download_active=is_heavy_download_active(),
        fast_interaction_active=is_fast_interaction_active(),
    )


def should_defer_cache_warm() -> bool:
    """Return True when post-completion cache warm should yield to protected UI."""
    return not get_system_load_controller().should_admit(
        WorkClass.CACHE_WARM,
        {"key": "cache_warm"},
        heavy_download_active=is_heavy_download_active(),
        fast_interaction_active=is_fast_interaction_active(),
    )


def cap_prefetch_radius(base_radius: int, *, fast_interaction_active: bool,
                        interaction_mode: str = '',
                        series_number: Optional[str] = None) -> int:
    """Cap prefetch radius, optionally relaxing for a completed series.

    When *series_number* is provided and the orchestrator confirms that series
    has finished downloading, the heavy_download_active override is cleared
    so the viewed series gets full prefetch radius even while the study is
    still downloading other series.  (v2.3.5 â€" Fix 2: series-level readiness)
    """
    heavy = is_heavy_download_active()
    if heavy and series_number is not None:
        if is_viewed_series_complete(series_number):
            heavy = False
    return get_system_load_controller().cap_prefetch_radius(
        base_radius,
        fast_interaction_active=fast_interaction_active,
        heavy_download_active=heavy,
        interaction_mode=interaction_mode,
    )


def is_viewed_series_complete(series_number) -> bool:
    """True when the specific series has finished downloading.

    Queries the PipelineOrchestrator (if registered) for per-series completion.
    Returns False if no orchestrator is available or the series is unknown.
    (v2.3.5 â€" Fix 2: series-level readiness)
    """
    if series_number is None:
        return False
    with _ORCHESTRATOR_LOCK:
        orch = _ACTIVE_ORCHESTRATOR
    if orch is None:
        return False
    try:
        return bool(orch.is_series_downloaded(str(series_number)))
    except Exception:
        return False


def should_rate_limit(key: Hashable, min_interval_ms: float, *, force: bool = False) -> bool:
    """True when an event for *key* should be skipped/coalesced."""
    now = _now_ms()
    with _LOCK:
        if force:
            _LAST_EVENT_MS[key] = now
            return False
        last = _LAST_EVENT_MS.get(key, 0.0)
        if now - last < float(min_interval_ms):
            return True
        _LAST_EVENT_MS[key] = now
        return False


def should_admit(task_type: WorkClass | str, context: Optional[dict] = None) -> bool:
    """Shared admission front door for FAST viewer background work."""
    ctx = dict(context or {})
    return get_system_load_controller().should_admit(
        task_type,
        ctx,
        heavy_download_active=is_heavy_download_active(),
        fast_interaction_active=is_fast_interaction_active(),
    )


def classify_work(task_type: WorkClass | str) -> BlockId:
    """Return the functional block that owns the requested FAST work class."""
    return get_system_load_controller().classify_work_class(task_type)


def get_load_debug_snapshot() -> dict[str, object]:
    """Return a consolidated FAST load/debug snapshot through the public facade."""
    return get_system_load_controller().debug_snapshot(
        heavy_download_active=is_heavy_download_active(),
        fast_interaction_active=is_fast_interaction_active(),
    )


def get_live_block_telemetry_snapshot(*, label: str = "") -> dict[str, object]:
    """Return a merged live per-block runtime snapshot for FAST diagnostics."""
    with _ORCHESTRATOR_LOCK:
        telemetry = _ACTIVE_BLOCK_TELEMETRY
        orch = _ACTIVE_ORCHESTRATOR
    if telemetry is None:
        telemetry = LiveBlockTelemetry(orchestrator=orch)
    return telemetry.snapshot(
        heavy_download_active=is_heavy_download_active(),
        fast_interaction_active=is_fast_interaction_active(),
        label=label,
    )


def get_live_block_history_snapshot(*, label: str = "") -> dict[str, object]:
    """Alias for callers that want the latest snapshot including history rollup."""
    return get_live_block_telemetry_snapshot(label=label)


def emit_live_block_telemetry(logger=None, *, label: str = "", snapshot: Optional[dict[str, object]] = None) -> dict[str, object]:
    """Emit a compact `[BLOCK_DIAG]` heartbeat for the live FAST runtime."""
    with _ORCHESTRATOR_LOCK:
        telemetry = _ACTIVE_BLOCK_TELEMETRY
        orch = _ACTIVE_ORCHESTRATOR
    if telemetry is None:
        telemetry = LiveBlockTelemetry(orchestrator=orch)
    return telemetry.emit_heartbeat(
        heavy_download_active=is_heavy_download_active(),
        fast_interaction_active=is_fast_interaction_active(),
        logger=logger,
        label=label,
        snapshot=snapshot,
    )
