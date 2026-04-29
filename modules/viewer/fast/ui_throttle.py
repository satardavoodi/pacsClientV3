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

import logging
import threading
import time
from typing import Hashable, Optional

from modules.viewer.fast.block_telemetry import LiveBlockTelemetry
from modules.viewer.fast.system_load_controller import get_system_load_controller
from modules.viewer.fast.system_load_controller import BlockId
from modules.viewer.fast.system_load_controller import WorkClass

_logger = logging.getLogger("aipacs.ui_throttle")

_LOCK = threading.Lock()
_LAST_EVENT_MS: dict[Hashable, float] = {}
_PROTECTED_DRAG_UNTIL_MS: float = 0.0
_PROTECTED_DRAG_ACTIVE: bool = False  # Explicit latch; True from begin() to end()
_PROTECTED_DRAG_BEGIN_MS: float = 0.0

# v2.3.8 R15: Parallel Advanced (VTK) viewer protected-interaction latch.
# Advanced mode wheel bursts and stack drags call
# ``record_advanced_protected_interaction(...)`` from the coalesce flush
# (begin + keepalive per frame) and GC re-enable (end). A separate latch
# is kept so FAST and Advanced paths stay distinguishable in
# ``[PROTECTED_*]`` log lines, but ``is_protected_drag_active()`` returns
# True if EITHER latch is active — so R3 (CACHE_WARM / PREFETCH denial),
# R4 (progressive grow defer — no-op for Advanced), and R5 (DM progress
# apply skip) automatically extend to Advanced without touching R5's call
# site in ``_apply_throttled_progress``.
_ADVANCED_PROTECTED_ACTIVE: bool = False
_ADVANCED_PROTECTED_UNTIL_MS: float = 0.0
_ADVANCED_PROTECTED_BEGIN_MS: float = 0.0

# v2.3.7 R13: cross-process drag-throttle signal.
# The download subprocess (opt-in) polls this file's mtime to decide
# whether to temporarily drop its OS priority during a protected drag.
# R13 DISABLED BY DEFAULT after log 99 (priority inversion on the
# IPC queue mutex caused ui_lag regression 229→412ms). Opt-in:
# AIPACS_DRAG_SUBPROC_THROTTLE=1 to enable both viewer-side touching
# and subprocess-side polling.
_DRAG_FLAG_PATH: Optional[str] = None
_DRAG_FLAG_LAST_TOUCH_MS: float = 0.0
_DRAG_FLAG_MIN_INTERVAL_MS: float = 200.0  # rate-limit fs writes


def _get_drag_flag_path() -> Optional[str]:
    global _DRAG_FLAG_PATH
    if _DRAG_FLAG_PATH is not None:
        return _DRAG_FLAG_PATH or None
    import os as _os
    if _os.environ.get("AIPACS_DRAG_SUBPROC_THROTTLE", "0") != "1":
        _DRAG_FLAG_PATH = ""
        return None
    try:
        from aipacs_runtime import user_data_root as _udr
        cache_dir = _udr() / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        _DRAG_FLAG_PATH = str(cache_dir / ".drag_active")
    except Exception:
        _DRAG_FLAG_PATH = ""
    return _DRAG_FLAG_PATH or None


def _touch_drag_flag() -> None:
    """Rate-limited touch of the drag-active flag file (fs mtime = now)."""
    global _DRAG_FLAG_LAST_TOUCH_MS
    path = _get_drag_flag_path()
    if not path:
        return
    now = _now_ms()
    if now - _DRAG_FLAG_LAST_TOUCH_MS < _DRAG_FLAG_MIN_INTERVAL_MS:
        return
    _DRAG_FLAG_LAST_TOUCH_MS = now
    try:
        # Open-append-close is the cheapest way to update mtime on Windows.
        with open(path, "ab") as _f:
            pass
        import os as _os
        _os.utime(path, None)
    except Exception:
        pass

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


def record_protected_drag(active: bool, *, grace_ms: float = 0.0) -> None:
    """Record whether the viewer is entering/leaving the protected drag lane.

    Protection uses an explicit boolean latch (``_PROTECTED_DRAG_ACTIVE``) for
    the body of the drag, plus a grace-window deadline (``_PROTECTED_DRAG_UNTIL_MS``)
    for the tail after the user releases the mouse. Call sites should do:

      * On drag start: ``record_protected_drag(True, grace_ms=1500)``
      * On each drag-move: ``keepalive_protected_drag(1500)`` (refreshes deadline)
      * On drag end:   ``record_protected_drag(False, grace_ms=250)``

    Emits ``[PROTECTED_DRAG]`` log lines on state transitions so log files can
    show exactly when the protected window was active. Also resets the
    SystemLoadController UI-tick baseline on begin/end so per-drag
    ``ui_lag_max_ms`` is not polluted by cross-session idle gaps.
    """
    global _PROTECTED_DRAG_UNTIL_MS, _PROTECTED_DRAG_ACTIVE, _PROTECTED_DRAG_BEGIN_MS
    now = _now_ms()
    grace = max(0.0, float(grace_ms))
    if active:
        was_active = _PROTECTED_DRAG_ACTIVE
        _PROTECTED_DRAG_ACTIVE = True
        _PROTECTED_DRAG_UNTIL_MS = now + grace if grace > 0.0 else 0.0
        if not was_active:
            _PROTECTED_DRAG_BEGIN_MS = now
            try:
                get_system_load_controller().reset_ui_tick_baseline()
            except Exception:
                pass
            _logger.info("[PROTECTED_DRAG] begin grace_ms=%.0f", grace)
        # v2.3.7 #3: always touch the cross-process drag flag so the
        # download subprocess can drop to IDLE priority promptly.
        _touch_drag_flag()
    else:
        was_active = _PROTECTED_DRAG_ACTIVE
        _PROTECTED_DRAG_ACTIVE = False
        # Soft-release: keep protection alive for `grace_ms` tail so the
        # last few coalesced updates don't land in a nominal window and
        # cause a visible jitter when the finger lifts.
        _PROTECTED_DRAG_UNTIL_MS = now + grace
        if was_active:
            duration_ms = now - _PROTECTED_DRAG_BEGIN_MS if _PROTECTED_DRAG_BEGIN_MS > 0.0 else 0.0
            _logger.info(
                "[PROTECTED_DRAG] end duration_ms=%.0f tail_grace_ms=%.0f",
                duration_ms,
                grace,
            )
            _PROTECTED_DRAG_BEGIN_MS = 0.0


def keepalive_protected_drag(grace_ms: float = 1500.0) -> None:
    """Refresh the protected-drag deadline without changing the latch.

    Call from the drag-move hook on every mouse-move delivery so the
    protected window covers the entire drag duration, even drags lasting
    many seconds. Cheap: single monotonic read + one assignment.
    """
    global _PROTECTED_DRAG_UNTIL_MS
    if not _PROTECTED_DRAG_ACTIVE:
        return
    # Keepalive only if the new deadline pushes the window later.
    new_deadline = _now_ms() + max(0.0, float(grace_ms))
    if new_deadline > _PROTECTED_DRAG_UNTIL_MS:
        _PROTECTED_DRAG_UNTIL_MS = new_deadline
    # v2.3.7 #3: refresh the cross-process drag flag (rate-limited internally).
    _touch_drag_flag()


def is_protected_drag_active() -> bool:
    # True while the explicit latch is set OR while the post-release grace
    # window has not yet expired.
    # v2.3.8 R15: also considers the Advanced (VTK) latch so R3/R4/R5
    # automatically extend to Advanced wheel/stack interactions.
    if _PROTECTED_DRAG_ACTIVE or _ADVANCED_PROTECTED_ACTIVE:
        return True
    now = _now_ms()
    if now <= float(_PROTECTED_DRAG_UNTIL_MS):
        return True
    if now <= float(_ADVANCED_PROTECTED_UNTIL_MS):
        return True
    return False


def record_advanced_protected_interaction(
    active: bool,
    *,
    grace_ms: float = 0.0,
    source: str = "",
) -> None:
    """Record Advanced (VTK) viewer protected wheel/stack interaction state.

    v2.3.8 R15: Advanced mode's ``_flush_pending_wheel_slice_impl`` is the
    single per-frame touch point that covers both wheel scrolls and stack
    drags routed through ``queue_interactive_slice_target``. That flush
    fires this with ``active=True`` + a 2500ms grace as a combined
    begin + keepalive signal. The scroll-burst GC re-enable timer
    (``_reenable_gc_impl``) fires this with ``active=False`` + a 250ms
    tail grace, mirroring FAST's ``record_protected_drag`` semantics.

    The latch is kept separate from FAST's ``_PROTECTED_DRAG_ACTIVE`` so
    ``[PROTECTED_*]`` log lines stay distinguishable, but
    ``is_protected_drag_active()`` OR's both latches so every existing
    protected-drag policy (R3 admission denial, R4 progressive defer —
    no-op for Advanced, R5 DM progress apply skip) extends automatically.

    The cross-process R13 drag flag is touched on every ``active=True``
    call (rate-limited to 200ms internally), so when
    ``AIPACS_DRAG_SUBPROC_THROTTLE=1`` is enabled, the download subprocess
    reacts to Advanced drags identically to FAST drags.
    """
    global _ADVANCED_PROTECTED_ACTIVE, _ADVANCED_PROTECTED_UNTIL_MS
    global _ADVANCED_PROTECTED_BEGIN_MS
    now = _now_ms()
    grace = max(0.0, float(grace_ms))
    if active:
        was_active = _ADVANCED_PROTECTED_ACTIVE
        _ADVANCED_PROTECTED_ACTIVE = True
        # Keepalive semantics: only extend the deadline forward.
        new_deadline = now + grace if grace > 0.0 else 0.0
        if new_deadline > _ADVANCED_PROTECTED_UNTIL_MS:
            _ADVANCED_PROTECTED_UNTIL_MS = new_deadline
        if not was_active:
            _ADVANCED_PROTECTED_BEGIN_MS = now
            try:
                get_system_load_controller().reset_ui_tick_baseline()
            except Exception:
                pass
            _logger.info(
                "[PROTECTED_ADVANCED] begin source=%s grace_ms=%.0f",
                source or "?", grace,
            )
        # R13 cross-process flag (no-op unless opt-in enabled).
        _touch_drag_flag()
    else:
        was_active = _ADVANCED_PROTECTED_ACTIVE
        _ADVANCED_PROTECTED_ACTIVE = False
        # Soft-release tail: keep R3/R5 protection alive for `grace_ms` so
        # the last few coalesced DM updates don't land inside a nominal
        # window right after the user releases the mouse.
        _ADVANCED_PROTECTED_UNTIL_MS = now + grace
        if was_active:
            duration_ms = (
                now - _ADVANCED_PROTECTED_BEGIN_MS
                if _ADVANCED_PROTECTED_BEGIN_MS > 0.0 else 0.0
            )
            _logger.info(
                "[PROTECTED_ADVANCED] end source=%s duration_ms=%.0f tail_grace_ms=%.0f",
                source or "?", duration_ms, grace,
            )
            _ADVANCED_PROTECTED_BEGIN_MS = 0.0


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
        fast_interaction_active=is_fast_interaction_active(),
    )


def progressive_grow_interval_ms() -> float:
    # Under a protected stack drag, defer viewer admission retries so the
    # grow timer does not wake the main thread every 150ms with deferred
    # no-op passes.  The drag keepalive grace is 1500ms; a 1500ms retry
    # interval aligns with that window and still admits the tail-grace
    # recheck promptly when the drag ends.  (v2.3.6 \u2014 low-config hardening)
    if is_protected_drag_active():
        return 1500.0
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
    """Return True when non-terminal grow work should yield to protected UI.

    Terminal completion is NEVER deferred (users must see completion immediately).
    Non-terminal grow is deferred whenever a stack drag is active so the main
    thread is not woken by background grow ticks during interaction.  This is
    especially important on low-config PCs where each grow tick can cost
    30-80ms.  (v2.3.6 — low-config hardening)
    """
    if not terminal and is_protected_drag_active():
        return True
    return not get_system_load_controller().should_admit(
        WorkClass.PROGRESSIVE_GROW,
        {"terminal": bool(terminal)},
        heavy_download_active=is_heavy_download_active(),
        fast_interaction_active=is_fast_interaction_active(),
    )


def should_defer_cache_warm() -> bool:
    """Return True when post-completion cache warm should yield to protected UI."""
    if is_protected_drag_active():
        return True
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

    NOTE: Protected drag is NOT capped to 0 here.  The pipeline's own
    `_prefetch_around()` already overrides `adaptive_radius` to a tight
    `_PROTECTED_DRAG_AHEAD_RADIUS` (=2) inside the protected-drag branch,
    and uses an explicit `should_admit(WorkClass.PREFETCH, ...)` per target.
    Returning 0 here would prevent the cache from growing during a long
    drag, leaving the user stuck on stale surrogate frames once they scroll
    past the initial cached window.  (v2.3.6 \u2014 game-changer #4)
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
    # Block all background work during protected drag (especially PREFETCH and CACHE_WARM)
    if is_protected_drag_active():
        if task_type == WorkClass.CACHE_WARM:
            return False
        if task_type == WorkClass.PREFETCH:
            # v2.3.7: pipeline-local P1 lane (tiny directional prefetch during
            # stack drag) is still admitted so the user's scroll direction has
            # pixels ready. Everything else (P2+ prefetch) is denied.
            # See playbook rule R3 and `_prefetch_around` `protected_drag` branch.
            try:
                priority = int(ctx.get("priority", 999))
            except Exception:
                priority = 999
            if priority > 1:  # FastWorkPriority.P1_NEIGHBOR == 1
                return False
        if task_type == WorkClass.FRAME_PREFETCH:
            # F6.1: mirror PREFETCH P1 rule for frame prefetch. During
            # protected drag the W/L+QImage build for the next directional
            # cached-pixel target is still useful (eliminates per-step
            # main-thread W/L cost); only admit P1, deny everything else.
            try:
                priority = int(ctx.get("priority", 999))
            except Exception:
                priority = 999
            if priority > 1:  # FastWorkPriority.P1_NEIGHBOR == 1
                return False
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
