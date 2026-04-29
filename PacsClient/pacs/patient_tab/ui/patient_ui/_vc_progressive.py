"""
Progressive display mixin for ViewerController.
Handles incremental viewer updates during series download.
"""
from __future__ import annotations
import asyncio
import threading
import time
from PySide6.QtCore import QTimer
from modules.zeta_boost import ImageSliceBooster
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing
from PacsClient.utils.series_completeness import build_series_completeness_snapshot
import logging

try:
    from modules.viewer.fast.ui_throttle import (
        progressive_grow_interval_ms as _ui_progressive_grow_interval_ms,
        progressive_signal_interval_ms as _ui_progressive_signal_interval_ms,
        should_admit as _ui_should_admit,
        should_defer_cache_warm as _ui_should_defer_cache_warm,
        should_defer_progressive_grow as _ui_should_defer_progressive_grow,
    )
except Exception:  # pragma: no cover - defensive for stripped test envs
    def _ui_progressive_grow_interval_ms() -> float:
        return 150.0

    def _ui_progressive_signal_interval_ms() -> float:
        return 100.0

    def _ui_should_defer_progressive_grow(*, terminal: bool = False) -> bool:
        return False

    def _ui_should_defer_cache_warm() -> bool:
        return False

    def _ui_should_admit(task_type, context=None) -> bool:
        return True

try:
    from modules.viewer.fast.slot_timing import emit_slot_timing as _g6_emit_slot_timing
except Exception:  # pragma: no cover
    def _g6_emit_slot_timing(*_a, **_k) -> bool:
        return False

logger = logging.getLogger(__name__)


_PROGRESSIVE_STATE_NO_VIEWER = "NO_VIEWER"
_PROGRESSIVE_STATE_AWAITING = "AWAITING"
_PROGRESSIVE_STATE_PROGRESSIVE = "PROGRESSIVE"
_PROGRESSIVE_STATE_COMPLETING = "COMPLETING"
_PROGRESSIVE_STATE_DONE = "DONE"
_FAST_PROGRESSIVE_INTERACTION_COOLDOWN_S = 1.25
_FAST_PROGRESSIVE_NONTERMINAL_GROW_MIN_INTERVAL_MS = 900.0
_FAST_PROGRESSIVE_NONTERMINAL_GROW_MAX_INTERVAL_MS = 2500.0
_FAST_PROGRESSIVE_FINALIZE_DEFER_BASE_MS = 350
_FAST_PROGRESSIVE_FINALIZE_DEFER_STEP_MS = 200
_FAST_PROGRESSIVE_FINALIZE_DEFER_MAX_RETRIES = 6


def _h10_log_progressive_mutation(obj, fn_name: str, mutated_sn: str, action: str):
    """[H10-4] Module-level helper â€” log progressive lifecycle mutation with context."""
    try:
        _vsn = '?'
        for _n in (getattr(obj, 'lst_nodes_viewer', None) or []):
            _vw = getattr(_n, 'vtk_widget', None)
            if _vw is not None:
                _vsn = str(getattr(getattr(_vw, 'image_viewer', None), 'metadata', {}).get('series', {}).get('series_number', '?'))
                break
        _dm = getattr(obj, '_h10_dm_active_series', getattr(getattr(obj, 'parent_widget', None), '_h10_dm_active_series', '?'))
        _prog_keys = list(getattr(obj, '_progressive_series', {}).keys())
        _done = list(getattr(obj, '_progressive_display_done', set()))
        logger.info(
            "[H10-4] fn=%s action=%s sn=%s viewer_series=%s dm_active=%s prog_keys=%s done=%s",
            fn_name, action, mutated_sn, _vsn, _dm, _prog_keys, _done,
        )
    except Exception:
        pass


def _cleanup_progressive_lifecycle_state(obj, series_number: str, source: str) -> None:
    """B4.3: centralized cleanup for progressive lifecycle guards.

    Module-level helper (not mixin method) so unit tests that bind selected
    mixin methods onto lightweight SimpleNamespace controllers do not need to
    bind an additional helper method.
    """
    sn = str(series_number)

    getattr(obj, '_progressive_series', {}).pop(sn, None)
    _h10_log_progressive_mutation(obj, '_cleanup_progressive_lifecycle_state', sn, f'pop_{source}')

    _clear_progressive_done_guard(obj, sn)
    _h10_log_progressive_mutation(obj, '_cleanup_progressive_lifecycle_state', sn, f'done_discard_{source}')
    _clear_layer2b_complete_guard(obj, sn)

    _set_progressive_lifecycle_state(
        obj,
        sn,
        _PROGRESSIVE_STATE_DONE,
        source="cleanup",
        reason=source,
    )


def _get_progressive_lifecycle_map(obj):
    """Return or lazily create lifecycle-state mapping on the controller."""
    state_map = getattr(obj, '_progressive_lifecycle_state', None)
    if state_map is None:
        state_map = {}
        setattr(obj, '_progressive_lifecycle_state', state_map)
    return state_map


def _get_progressive_lifecycle_state(obj, series_number: str) -> str:
    """Get lifecycle state for a series, defaulting to NO_VIEWER."""
    sn = str(series_number)
    state_map = _get_progressive_lifecycle_map(obj)
    return str(state_map.get(sn, _PROGRESSIVE_STATE_NO_VIEWER))


def _set_progressive_lifecycle_state(
    obj,
    series_number: str,
    new_state: str,
    *,
    source: str,
    reason: str = "",
) -> str:
    """Set lifecycle state for a series and emit a low-noise transition log."""
    sn = str(series_number)
    state_map = _get_progressive_lifecycle_map(obj)
    old_state = str(state_map.get(sn, _PROGRESSIVE_STATE_NO_VIEWER))
    state_map[sn] = str(new_state)

    if old_state != new_state:
        try:
            logger.info(
                "progressive-state: series=%s %s -> %s source=%s reason=%s",
                sn, old_state, new_state, source, reason,
            )
        except Exception:
            pass
    return old_state


def _get_progressive_done_set(obj):
    """Return or lazily create legacy done-guard set (compatibility)."""
    done = getattr(obj, '_progressive_display_done', None)
    if done is None:
        done = set()
        setattr(obj, '_progressive_display_done', done)
    return done


def _is_progressive_done_guard_active(obj, series_number: str) -> bool:
    """Unified done-guard check via legacy set + lifecycle state-map."""
    sn = str(series_number)
    if sn in _get_progressive_done_set(obj):
        return True
    return _get_progressive_lifecycle_state(obj, sn) in {
        _PROGRESSIVE_STATE_PROGRESSIVE,
        _PROGRESSIVE_STATE_COMPLETING,
    }


def _mark_progressive_done_guard(obj, series_number: str):
    """Mark done-guard set for compatibility checks."""
    _get_progressive_done_set(obj).add(str(series_number))


def _clear_progressive_done_guard(obj, series_number: str):
    """Clear done-guard set for a series (idempotent)."""
    _get_progressive_done_set(obj).discard(str(series_number))


def _get_progressive_inflight_set(obj):
    """Return or lazily create legacy inflight guard set (compatibility)."""
    inflight = getattr(obj, '_progressive_display_inflight', None)
    if inflight is None:
        inflight = set()
        setattr(obj, '_progressive_display_inflight', inflight)
    return inflight


def _get_progressive_untargeted_defer_set(obj):
    """Return or lazily create the untargeted-background defer guard set."""
    deferred = getattr(obj, '_progressive_untargeted_defer', None)
    if deferred is None:
        deferred = set()
        setattr(obj, '_progressive_untargeted_defer', deferred)
    return deferred


def _is_progressive_untargeted_deferred(obj, series_number: str) -> bool:
    """True when untargeted first-display was previously deferred for this series."""
    return str(series_number) in _get_progressive_untargeted_defer_set(obj)


def _mark_progressive_untargeted_deferred(obj, series_number: str) -> None:
    """Mark a series as deferred until layout eligibility changes."""
    _get_progressive_untargeted_defer_set(obj).add(str(series_number))


def _clear_progressive_untargeted_deferred(obj, series_number: str) -> None:
    """Clear the untargeted-deferred guard for a series."""
    _get_progressive_untargeted_defer_set(obj).discard(str(series_number))


def _is_progressive_inflight(obj, series_number: str) -> bool:
    """Unified inflight check via legacy set + lifecycle state-map."""
    sn = str(series_number)
    if sn in _get_progressive_inflight_set(obj):
        return True
    return _get_progressive_lifecycle_state(obj, sn) == _PROGRESSIVE_STATE_AWAITING


def _is_progressive_start_task_inflight(obj, series_number: str) -> bool:
    """True only while the first-display task has been started."""
    return str(series_number) in _get_progressive_inflight_set(obj)


def _mark_progressive_inflight(obj, series_number: str):
    """Mark inflight guard (legacy set + lifecycle state)."""
    sn = str(series_number)
    _get_progressive_inflight_set(obj).add(sn)
    _set_progressive_lifecycle_state(
        obj,
        sn,
        _PROGRESSIVE_STATE_AWAITING,
        source="inflight_guard",
        reason="mark_inflight",
    )


def _clear_progressive_inflight(obj, series_number: str):
    """Clear inflight guard (legacy set only; state transitions happen elsewhere)."""
    _get_progressive_inflight_set(obj).discard(str(series_number))


def _get_series_download_completed_set(obj):
    """Return or lazily create the completed-series guard set."""
    completed = getattr(obj, '_series_download_completed', None)
    if completed is None:
        completed = set()
        setattr(obj, '_series_download_completed', completed)
    return completed


def _is_series_download_completed(obj, series_number: str) -> bool:
    """True when a series has already completed in this controller lifetime."""
    return str(series_number) in _get_series_download_completed_set(obj)


def _mark_series_download_completed(obj, series_number: str) -> None:
    """Record a series as completed for late-progress / late-callback guards."""
    _get_series_download_completed_set(obj).add(str(series_number))


def _clear_series_download_completed(obj, series_number: str) -> None:
    """Clear completed-series guard for a verified new progressive cycle."""
    _get_series_download_completed_set(obj).discard(str(series_number))


def _should_restart_after_done(obj, series_number: str, downloaded: int, total: int) -> bool:
    """True when a completed series is receiving a real new partial cycle."""
    sn = str(series_number)
    if downloaded >= total:
        return False
    if _get_progressive_lifecycle_state(obj, sn) != _PROGRESSIVE_STATE_DONE:
        return False
    if sn in getattr(obj, '_progressive_series', {}):
        return False
    try:
        if obj._find_progressive_viewers(sn):
            return False
    except Exception:
        return False
    return True


def _progressive_signal_interval_ms() -> float:
    """Progressive callback rate: normal 10 Hz, protected 2 Hz."""
    return float(_ui_progressive_signal_interval_ms())


def _progressive_grow_interval_ms() -> float:
    """Viewer admission retry cadence for non-terminal progressive growth."""
    return float(_ui_progressive_grow_interval_ms())


def _should_defer_progressive_grow(*, terminal: bool = False) -> bool:
    """Helper front door for progressive grow deferral decisions."""
    return bool(_ui_should_defer_progressive_grow(terminal=terminal))


def _is_timer_active(timer_obj) -> bool:
    """Best-effort timer active probe that also works with test doubles."""
    if timer_obj is None:
        return False
    try:
        return bool(timer_obj.isActive())
    except Exception:
        return bool(getattr(timer_obj, "_active", False))


def _is_fast_progressive_interaction_hot(viewers: list) -> bool:
    """True when FAST interaction is still active/settling for any viewer.

    This is intentionally conservative: if drag/wheel settle windows are still
    active, defer non-terminal progressive grow so expensive grow/remap work
    does not compete with immediate interaction responsiveness.
    """
    for vtk_w, _ in viewers or []:
        if not bool(getattr(vtk_w, "_qt_bridge_active", False)):
            continue
        bridge = getattr(vtk_w, "image_viewer", None)
        if bridge is None:
            continue
        if bool(getattr(bridge, "_stack_drag_active", False)):
            return True
        if bool(getattr(bridge, "_protected_drag_active", False)):
            return True
        if _is_timer_active(getattr(bridge, "_interaction_settle_timer", None)):
            return True
        qt_viewer = getattr(bridge, "qt_viewer", None)
        if _is_timer_active(getattr(qt_viewer, "_scroll_stop_timer", None)):
            return True
        pipeline = getattr(bridge, "pipeline", None)
        if bool(getattr(pipeline, "_fast_interaction", False)):
            return True
        # Keep non-terminal progressive grow deferred for a short cooldown
        # after the last wheel/drag event to avoid immediate grow/remap
        # contention during micro-pauses in active stack sessions.
        try:
            recent_hot_probe = getattr(bridge, "is_recent_interaction_hot", None)
            if callable(recent_hot_probe):
                if bool(recent_hot_probe(_FAST_PROGRESSIVE_INTERACTION_COOLDOWN_S)):
                    return True
            else:
                last_evt = float(getattr(bridge, "_last_interaction_event_monotonic", 0.0) or 0.0)
                if last_evt > 0.0:
                    age_s = float(time.perf_counter() - last_evt)
                    if age_s <= float(_FAST_PROGRESSIVE_INTERACTION_COOLDOWN_S):
                        return True
        except Exception:
            pass
    return False


def _should_defer_cache_warm() -> bool:
    """Helper front door for post-completion cache-warm deferral decisions."""
    return bool(_ui_should_defer_cache_warm())


def _should_admit_cache_warm(obj, series_number: str) -> bool:
    """Admission front door for post-completion cache warm dispatch."""
    return bool(_ui_should_admit(
        "cache_warm",
        {
            "key": f"cache-warm:{id(obj)}:{series_number}",
            "series_key": str(series_number),
        },
    ))


def _should_admit_progressive_signal(obj, series_number: str, *, terminal: bool = False) -> bool:
    """Admission front door for viewer-facing progressive progress work."""
    if terminal:
        return True
    return bool(_ui_should_admit(
        "progressive_signal",
        {
            "key": f"progressive-signal:{id(obj)}:{series_number}",
            "series_key": str(series_number),
            "terminal": bool(terminal),
        },
    ))


def _restart_progressive_grow_timer(obj, delay_ms: float | None = None) -> None:
    """Start the single-shot grow timer with an optional retry delay."""
    timer = getattr(obj, '_progressive_grow_timer', None)
    if timer is None:
        return
    default_delay = getattr(obj, '_progressive_grow_timer_default_interval_ms', 150)
    target_delay = int(max(1, round(delay_ms if delay_ms is not None else default_delay)))
    try:
        if hasattr(timer, 'setInterval'):
            timer.setInterval(target_delay)
    except Exception:
        pass
    try:
        timer.start()
    except Exception:
        pass


def _get_progressive_admit_batch_size(obj) -> int:
    """Return the max non-terminal slice window admitted per grow tick."""
    fallback = getattr(obj, '_progressive_admit_batch_size_default', 8)
    try:
        return max(1, int(getattr(obj, '_progressive_admit_batch_size', fallback) or fallback))
    except Exception:
        return max(1, int(fallback or 8))


def _get_layer2b_complete_guard_set(obj):
    """Return or lazily create the Layer 2b duplicate-completion guard set."""
    complete_guard = getattr(obj, '_layer2b_complete_guard', None)
    if complete_guard is None:
        complete_guard = set()
        setattr(obj, '_layer2b_complete_guard', complete_guard)
    return complete_guard


def _is_layer2b_complete_guard_active(obj, series_number: str) -> bool:
    """True when Layer 2b completion has already run for this series."""
    return str(series_number) in _get_layer2b_complete_guard_set(obj)


def _mark_layer2b_complete_guard(obj, series_number: str) -> None:
    """Mark Layer 2b completion as processed for a series."""
    _get_layer2b_complete_guard_set(obj).add(str(series_number))


def _clear_layer2b_complete_guard(obj, series_number: str) -> None:
    """Clear Layer 2b duplicate-completion guard for a series."""
    _get_layer2b_complete_guard_set(obj).discard(str(series_number))


def _get_progressive_terminal_complete_guard_set(obj):
    """Return or lazily create the terminal-complete one-shot guard set."""
    guard = getattr(obj, '_progressive_terminal_complete_guard', None)
    if guard is None:
        guard = set()
        setattr(obj, '_progressive_terminal_complete_guard', guard)
    return guard


def _is_progressive_terminal_complete_guard_active(obj, series_number: str) -> bool:
    """True after the fast progressive path already observed terminal completion."""
    return str(series_number) in _get_progressive_terminal_complete_guard_set(obj)


def _mark_progressive_terminal_complete_guard(obj, series_number: str) -> None:
    """Record that terminal completion was already observed for this cycle."""
    _get_progressive_terminal_complete_guard_set(obj).add(str(series_number))


def _clear_progressive_terminal_complete_guard(obj, series_number: str) -> None:
    """Clear the terminal-complete guard for a verified new cycle."""
    _get_progressive_terminal_complete_guard_set(obj).discard(str(series_number))


def _get_progressive_finalized_series_set(obj):
    """Return or lazily create the terminal-finalization one-shot guard set."""
    guard = getattr(obj, '_progressive_finalized_series', None)
    if guard is None:
        guard = set()
        setattr(obj, '_progressive_finalized_series', guard)
    return guard


def _is_progressive_finalized(obj, series_number: str) -> bool:
    """True once terminal finalization has already run for this cycle."""
    return str(series_number) in _get_progressive_finalized_series_set(obj)


def _mark_progressive_finalized(obj, series_number: str) -> None:
    """Mark a series as terminal-finalized for this cycle."""
    _get_progressive_finalized_series_set(obj).add(str(series_number))


def _clear_progressive_finalized(obj, series_number: str) -> None:
    """Clear terminal-finalized guard for a verified new cycle."""
    _get_progressive_finalized_series_set(obj).discard(str(series_number))


def _get_progressive_finalize_defer_set(obj):
    """Return or lazily create the in-flight finalize defer guard set."""
    guard = getattr(obj, '_progressive_finalize_defer_pending', None)
    if guard is None:
        guard = set()
        setattr(obj, '_progressive_finalize_defer_pending', guard)
    return guard


def _get_layer2b_defer_pending_set(obj):
    """[F9] Return or lazily create the Layer 2b body defer guard set.

    Tracks series whose ``_on_series_download_fully_complete_impl`` body has
    been deferred via ``QTimer.singleShot`` and is awaiting retry. Separate
    from ``_progressive_finalize_defer_pending`` (which is the inner
    ``_finalize_progressive_series`` retry, much later in the pipeline).
    """
    guard = getattr(obj, '_layer2b_defer_pending', None)
    if guard is None:
        guard = set()
        setattr(obj, '_layer2b_defer_pending', guard)
    return guard


def _get_layer2b_defer_retry_map(obj):
    """[F9] Return or lazily create the per-series Layer 2b retry counter."""
    counter = getattr(obj, '_layer2b_defer_retry_count', None)
    if counter is None:
        counter = {}
        setattr(obj, '_layer2b_defer_retry_count', counter)
    return counter


def _get_terminal_grow_defer_retry_map(obj):
    """[F10] Return or lazily create the per-series terminal-grow retry counter.

    Used by ``_flush_progressive_grow_impl`` to defer terminal
    ``_grow_progressive_fast`` calls when a viewer is in a hot FAST drag.
    R4 says terminal completion always fires; F10 honors that by
    force-running after _FAST_PROGRESSIVE_FINALIZE_DEFER_MAX_RETRIES retries.
    """
    counter = getattr(obj, '_terminal_grow_defer_retry_count', None)
    if counter is None:
        counter = {}
        setattr(obj, '_terminal_grow_defer_retry_count', counter)
    return counter


def _match_viewers_for_series(obj, sn: str) -> list:
    """[F9] Quick scan returning [(vtk_w, node)] for viewers showing series ``sn``.

    Used by the Layer 2b defer gate to test ``_is_fast_progressive_interaction_hot``
    without entering the heavy completion body. Cheap: only attribute reads.
    """
    matched = []
    for node in getattr(obj, 'lst_nodes_viewer', None) or []:
        vtk_w = getattr(node, "vtk_widget", None)
        if vtk_w is None:
            continue
        is_match = (getattr(vtk_w, "_progressive_series_number", None) == sn)
        if not is_match:
            try:
                viewer_sn = str(
                    getattr(vtk_w.image_viewer, "metadata", {})
                    .get("series", {}).get("series_number", "")
                )
                is_match = (viewer_sn == sn)
            except Exception:
                pass
        if is_match:
            matched.append((vtk_w, node))
    return matched


def _finalize_progressive_series(
    obj,
    series_number: str,
    *,
    final_count: int = 0,
    viewers: list | None = None,
    source: str,
    dispatch_cache_warm: bool = False,
    _defer_retry: int = 0,
) -> bool:
    """Single terminal authority for progressive completion.

    Module-level helper so tests that bind only selected mixin methods onto
    lightweight controllers still exercise the real finalization path.
    """
    sn = str(series_number)
    if _is_progressive_finalized(obj, sn):
        getattr(obj, 'logger', logger).debug(
            "progressive: finalize skipped duplicate series=%s source=%s",
            sn, source,
        )
        return False

    matched_viewers = list(viewers or [])
    if not matched_viewers:
        for node in getattr(obj, 'lst_nodes_viewer', None) or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None:
                continue
            try:
                viewer_sn = str(
                    getattr(vtk_w.image_viewer, "metadata", {})
                    .get("series", {}).get("series_number", "")
                )
            except Exception:
                viewer_sn = ""
            if viewer_sn == sn or getattr(vtk_w, "_progressive_series_number", None) == sn:
                matched_viewers.append((vtk_w, node))

    # Do not run terminal finalize work while FAST interaction is still hot.
    # This specifically avoids UI stalls when completion arrives during/just
    # after stack drag on the same viewed series.
    if matched_viewers and _is_fast_progressive_interaction_hot(matched_viewers):
        if _defer_retry < _FAST_PROGRESSIVE_FINALIZE_DEFER_MAX_RETRIES:
            pending = _get_progressive_finalize_defer_set(obj)
            if sn not in pending:
                pending.add(sn)
                delay_ms = int(
                    _FAST_PROGRESSIVE_FINALIZE_DEFER_BASE_MS
                    + (_defer_retry * _FAST_PROGRESSIVE_FINALIZE_DEFER_STEP_MS)
                )

                def _retry_finalize(
                    _sn=sn,
                    _final_count=int(final_count),
                    _source=str(source),
                    _dispatch=bool(dispatch_cache_warm),
                    _next_retry=int(_defer_retry) + 1,
                ):
                    try:
                        _get_progressive_finalize_defer_set(obj).discard(_sn)
                    except Exception:
                        pass
                    try:
                        _finalize_progressive_series(
                            obj,
                            _sn,
                            final_count=_final_count,
                            viewers=None,
                            source=_source,
                            dispatch_cache_warm=_dispatch,
                            _defer_retry=_next_retry,
                        )
                    except Exception as _rf_exc:
                        getattr(obj, 'logger', logger).debug(
                            "progressive: deferred finalize retry failed series=%s source=%s retry=%d: %s",
                            _sn, _source, _next_retry, _rf_exc,
                        )

                QTimer.singleShot(delay_ms, _retry_finalize)
            getattr(obj, 'logger', logger).debug(
                "progressive: finalize deferred interaction-hot series=%s source=%s retry=%d",
                sn, source, _defer_retry + 1,
            )
            return False
        getattr(obj, 'logger', logger).warning(
            "progressive: finalize forcing after defer retries series=%s source=%s retry=%d",
            sn, source, _defer_retry,
        )

    _get_progressive_finalize_defer_set(obj).discard(sn)

    # G6: time the actual terminal work block (force-run path is the suspect).
    _g6_t0 = time.perf_counter()
    _g6_was_force = bool(_defer_retry >= _FAST_PROGRESSIVE_FINALIZE_DEFER_MAX_RETRIES)

    _mark_progressive_finalized(obj, sn)
    _mark_progressive_terminal_complete_guard(obj, sn)
    _mark_series_download_completed(obj, sn)
    _set_progressive_lifecycle_state(
        obj,
        sn,
        _PROGRESSIVE_STATE_COMPLETING,
        source="_finalize_progressive_series",
        reason=source,
    )

    for vtk_w, _node in matched_viewers:
        try:
            if getattr(vtk_w, "_progressive_mode", False):
                vtk_w.exit_progressive_mode()
        except Exception as _epm_exc:
            getattr(obj, 'logger', logger).warning(
                "progressive: exit_progressive_mode failed viewer_id=%s series=%s (%s): %s",
                getattr(vtk_w, "id_vtk_widget", id(vtk_w)), sn, source, _epm_exc,
            )
        try:
            iv = getattr(vtk_w, "image_viewer", None)
            if iv is not None and hasattr(iv, "update_corners_actors"):
                iv.update_corners_actors()
        except Exception:
            pass

    if final_count > 0:
        obj._refresh_and_sync_metadata(sn, final_count)
        obj._invalidate_series_caches(sn)
        obj._update_thumbnail_count(sn, final_count)

    _cleanup_progressive_lifecycle_state(obj, sn, source=source)

    if dispatch_cache_warm and matched_viewers:
        obj._dispatch_post_completion_cache_warm(sn, matched_viewers)

    getattr(obj, 'logger', logger).info(
        "progressive: finalized series=%s count=%d source=%s",
        sn, final_count, source,
    )
    try:
        _g6_emit_slot_timing(
            "progressive.finalize_terminal",
            (time.perf_counter() - _g6_t0) * 1000.0,
            series=sn,
            extra={
                "source": source,
                "force": "1" if _g6_was_force else "0",
                "viewers": len(matched_viewers),
                "final_count": int(final_count),
            },
        )
    except Exception:
        pass
    return True


class _VCProgressiveMixin:
    """Auto-split mixin â€” see patient_widget_viewer_controller.py for history."""

    def on_series_images_progress(self, series_number: str, downloaded: int, total: int):
        """Qt signal slot: outer guard so exceptions never escape into Qt dispatch.

        Any unhandled exception in a Qt signal slot causes Qt's C++ abort() â€” a
        hard exit with no Python traceback that orphans the download subprocess.
        The real implementation is in ``_on_series_images_progress_impl``.
        """
        try:
            self._on_series_images_progress_impl(series_number, downloaded, total)
        except Exception as exc:
            try:
                viewer_count = len(self._find_progressive_viewers(str(series_number)))
            except Exception:
                viewer_count = -1
            try:
                fast_mode = self._is_fast_viewer_mode()
            except Exception:
                fast_mode = "?"
            self.logger.error(
                "progressive: unhandled error in on_series_images_progress "
                "series=%s downloaded=%d total=%d viewer_count=%d fast_mode=%s: %s",
                series_number, downloaded, total, viewer_count, fast_mode,
                exc, exc_info=True,
            )

    def _on_series_images_progress_impl(self, series_number: str, downloaded: int, total: int):
        """Called when new images for a series have been downloaded.

        Triggers progressive display: first batch opens the viewer, subsequent
        batches grow the volume in-place so the user sees progress live.

        Only active in FAST (PyDicom) mode.  In Advanced (VTK) mode the full
        series must be downloaded before display â€” series_downloaded handles that.

        Throttled to max once per 100ms per series to avoid CPU spikes when
        progress signals fire rapidly (one per downloaded file).
        """
        sn = str(series_number)
        if total <= 0 or downloaded <= 0:
            return

        def _has_viewer_interest_for_series() -> bool:
            for node in self.lst_nodes_viewer or []:
                vtk_w = getattr(node, "vtk_widget", None)
                if vtk_w is None:
                    continue
                if getattr(vtk_w, "_awaiting_series_number", None) == sn:
                    return True
                if getattr(vtk_w, "_progressive_series_number", None) == sn:
                    return True
                try:
                    viewer_sn = str(
                        getattr(vtk_w.image_viewer, "metadata", {})
                        .get("series", {}).get("series_number", "")
                    )
                except Exception:
                    viewer_sn = ""
                if viewer_sn == sn:
                    return True
            return False

        # Advanced (VTK) mode: skip progressive display entirely.
        # The series will be loaded once via series_downloaded signal.
        if not self._is_fast_viewer_mode():
            return

        if downloaded < total and not _should_admit_progressive_signal(self, str(series_number), terminal=False):
            return

        # Terminal idempotence: once this cycle already reached COMPLETE
        # (or Layer 2b has begun), reject duplicate terminal progress callbacks
        # before they recreate _progressive_series and re-enter one-shot grow.
        if downloaded >= total:
            if _is_progressive_finalized(self, sn):
                logger.info(
                    "progressive: duplicate terminal progress ignored series=%s downloaded=%d total=%d guard=finalized",
                    sn, downloaded, total,
                )
                logger.debug("progressive: duplicate_load_suppressed series=%s guard=finalized", sn)
                return
            if _is_progressive_terminal_complete_guard_active(self, sn):
                _set_progressive_lifecycle_state(
                    self,
                    sn,
                    _get_progressive_lifecycle_state(self, sn),
                    source="on_series_images_progress",
                    reason="duplicate_terminal_progress_guard",
                )
                logger.info(
                    "progressive: duplicate terminal progress ignored series=%s downloaded=%d total=%d guard=terminal_complete",
                    sn, downloaded, total,
                )
                return
            if _is_layer2b_complete_guard_active(self, sn):
                _set_progressive_lifecycle_state(
                    self,
                    sn,
                    _PROGRESSIVE_STATE_COMPLETING,
                    source="on_series_images_progress",
                    reason="duplicate_terminal_progress_layer2b",
                )
                logger.info(
                    "progressive: duplicate terminal progress ignored series=%s downloaded=%d total=%d guard=layer2b",
                    sn, downloaded, total,
                )
                return
            try:
                untargeted_background_complete = not _has_viewer_interest_for_series()
            except Exception:
                untargeted_background_complete = False
            if untargeted_background_complete:
                _mark_progressive_terminal_complete_guard(self, sn)
                _mark_progressive_untargeted_deferred(self, sn)
                self.logger.info(
                    "progressive: terminal background completion deferred to load_series_on_demand "
                    "series=%s downloaded=%d total=%d",
                    sn, downloaded, total,
                )
                return

        # H6 defense-in-depth: reject late progress signals for series that
        # have already completed.  Without this, late DM signals could
        # re-create _progressive_series tracking for a finished series.
        if _is_series_download_completed(self, sn):
            if _should_restart_after_done(self, sn, downloaded, total):
                _clear_series_download_completed(self, sn)
                _clear_layer2b_complete_guard(self, sn)
                _clear_progressive_terminal_complete_guard(self, sn)
                _clear_progressive_finalized(self, sn)
                logger.info(
                    "progressive: restart_after_done series=%s downloaded=%d total=%d",
                    sn, downloaded, total,
                )
            else:
                _set_progressive_lifecycle_state(
                    self,
                    sn,
                    _PROGRESSIVE_STATE_DONE,
                    source="on_series_images_progress",
                    reason="already_completed_guard",
                )
                logger.info(
                    "[H7-P7] series=%s downloaded=%d total=%d action=rejected_H6_completed",
                    sn, downloaded, total,
                )
                logger.debug("progressive: stale_request_drop series=%s guard=H6_completed", sn)
                return

        # Block B optimization: untargeted FAST background series should remain
        # loader-only until an explicit viewer request exists.  Short-circuit
        # BEFORE creating progressive lifecycle entries or calling
        # _start_progressive_display(target=None), which only logs/deferred-cleans
        # and adds control-plane churn under download overlap.
        try:
            untargeted_loader_only = (
                downloaded < total
                and downloaded >= self._progressive_grow_batch_size
                and not _has_viewer_interest_for_series()
            )
        except Exception:
            untargeted_loader_only = False
        if untargeted_loader_only:
            if not _is_progressive_untargeted_deferred(self, sn):
                _mark_progressive_untargeted_deferred(self, sn)
                self.logger.info(
                    "progressive: untargeted background progress deferred series=%s "
                    "downloaded=%d total=%d -- loader-only until explicit viewer request",
                    sn, downloaded, total,
                )
            return

        # [H7-P7] Entry log â€” captures all guard states at entry
        _done_active = _is_progressive_done_guard_active(self, sn)
        _inflight_active = _is_progressive_inflight(self, sn)
        # B3.5: Demoted viewer iteration loop to DEBUG — adds ~0.5-1ms
        # per progress signal on main thread.  Only runs for diagnostics.
        if logger.isEnabledFor(logging.DEBUG):
            _viewers_prog = []
            _viewers_nonprog = []
            for _n in (self.lst_nodes_viewer or []):
                _vw = getattr(_n, "vtk_widget", None)
                if _vw is None:
                    continue
                try:
                    _vsn = str(
                        getattr(_vw.image_viewer, "metadata", {})
                        .get("series", {}).get("series_number", "")
                    )
                except Exception:
                    _vsn = ""
                if _vsn == sn:
                    if _vw._progressive_mode:
                        _viewers_prog.append(_vsn)
                    else:
                        _viewers_nonprog.append(_vsn)
            logger.debug(
                "[H7-P7] series=%s downloaded=%d total=%d fast_mode=True "
                "in_completed_set=False in_done_set=%s in_inflight_set=%s "
                "in_progressive_series=%s viewers_prog=%d viewers_nonprog=%d",
                sn, downloaded, total,
                _done_active, _inflight_active,
                sn in self._progressive_series,
                len(_viewers_prog), len(_viewers_nonprog),
            )

        # Track this series for progressive updates
        if sn not in self._progressive_series:
            self._progressive_series[sn] = {"total": total, "last_grow_count": 0, "last_signal_ms": 0}
            _h10_log_progressive_mutation(self, 'on_series_images_progress_impl', sn, 'add_key')
            _set_progressive_lifecycle_state(
                self,
                sn,
                _PROGRESSIVE_STATE_AWAITING,
                source="on_series_images_progress",
                reason="first_progress_signal",
            )
        info = self._progressive_series[sn]
        info["total"] = max(info["total"], total)

        # â”€â”€ Throttle: skip if called less than 250ms ago for this series
        #    (always process 'download complete' signals though) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        now_ms_val = time.monotonic() * 1000
        if downloaded < total and (now_ms_val - info.get("last_signal_ms", 0)) < _progressive_signal_interval_ms():
            return
        info["last_signal_ms"] = now_ms_val

        # Check if a viewer is already displaying this series in progressive mode
        viewers_showing = self._find_progressive_viewers(sn)
        if viewers_showing:
            _set_progressive_lifecycle_state(
                self,
                sn,
                _PROGRESSIVE_STATE_PROGRESSIVE,
                source="on_series_images_progress",
                reason="progressive_viewer_present",
            )
            # Only grow when enough NEW images arrived (batch boundary)
            delta = downloaded - info["last_grow_count"]
            if delta >= self._progressive_grow_batch_size or downloaded >= total:
                info["pending_downloaded"] = downloaded
                if not self._progressive_grow_timer.isActive():
                    _restart_progressive_grow_timer(self, _progressive_grow_interval_ms())
            return

        # Check if a viewer already shows this series (non-progressive, e.g. the
        # user drag-dropped during an active download so change_series_on_viewer
        # loaded whatever files were on disk at that moment without entering
        # progressive mode).  Two sub-cases:
        #
        #   downloaded < total  â€” still downloading: activate progressive mode
        #                         retroactively so future grow ticks will fire.
        #   downloaded >= total â€” download just completed: the last N images may
        #                         have all arrived in one batch so no intermediate
        #                         signal could activate progressive mode.  Do a
        #                         single final grow immediately to expose those
        #                         images.  The "live connection" between viewer
        #                         and download ends here â€” no more signals come.
        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None or vtk_w._progressive_mode:
                continue
            try:
                viewer_sn = str(
                    getattr(vtk_w.image_viewer, "metadata", {})
                    .get("series", {}).get("series_number", "")
                )
            except Exception:
                viewer_sn = ""
            if viewer_sn != sn:
                continue

            if downloaded < total:
                # Still downloading â€” activate progressive mode retroactively
                avail = vtk_w.image_viewer.get_count_of_slices() if vtk_w.image_viewer else 0
                vtk_w.enter_progressive_mode(total, sn)
                vtk_w.update_available_slice_count(avail)
                _set_progressive_lifecycle_state(
                    self,
                    sn,
                    _PROGRESSIVE_STATE_PROGRESSIVE,
                    source="on_series_images_progress",
                    reason="retroactive_activation",
                )
                slider = getattr(node, "slider", None)
                if slider is not None:
                    try:
                        slider.blockSignals(True)
                        slider.setMaximum(max(0, total - 1))
                        slider.blockSignals(False)
                    except Exception:
                        pass
                # Fast mode: activate آ±20 booster for the active series
                if self._is_fast_viewer_mode():
                    try:
                        loader = getattr(vtk_w, "_lazy_loader", None)
                        backend = getattr(loader, "backend", None) if loader is not None else None
                        if backend is not None:
                            paths = backend.get_file_paths()
                            if paths:
                                self._image_slice_booster.set_active(sn, paths, center_slice=0)
                    except Exception:
                        pass
                info["last_grow_count"] = avail
                self.logger.info(
                    "progressive: retroactive activate series=%s avail=%d total=%d",
                    sn, avail, total,
                )
            else:
                # Download COMPLETE â€” one-shot final grow so the viewer shows
                # all downloaded images (covers the "last batch arrived at once"
                # scenario that bypassed retroactive activation).
                _set_progressive_lifecycle_state(
                    self,
                    sn,
                    _PROGRESSIVE_STATE_COMPLETING,
                    source="on_series_images_progress",
                    reason="done_guard_one_shot",
                )
                self.logger.info(
                    "progressive: one-shot final grow series=%s downloaded=%d total=%d",
                    sn, downloaded, total,
                )
                self._grow_progressive_fast(sn, downloaded, [(vtk_w, node)])
            return  # Handled â€” exit after first matching viewer

        # No viewer showing this series yet â€” start first progressive display.
        # Guard: only trigger once per series to avoid spawning dozens of
        # concurrent load tasks that spike CPU.
        # _progressive_display_done persists beyond inflight to prevent re-entry
        # when the series download completes (downloaded==total) after the first
        # progressive display already succeeded.

        # Check for viewers awaiting this series (drag-drop while download
        # was still in progress â€” spinner is already visible).
        _awaiting_viewer = None
        _awaiting_node = None
        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None:
                continue
            if getattr(vtk_w, "_awaiting_series_number", None) == sn:
                _awaiting_viewer = vtk_w
                _awaiting_node = node
                break

        _allow_untargeted_first_display = (_awaiting_viewer is not None)

        if _awaiting_viewer is not None:
            _clear_progressive_untargeted_deferred(self, sn)

        if downloaded >= self._progressive_grow_batch_size:
            if _is_progressive_done_guard_active(self, sn):
                # Already displayed once — grow path should handle updates.
                # Defensive: if progressive mode was lost (e.g. race between
                # threaded done.add and activation, or switch_series skipped
                # progressive entry), re-enter progressive mode so the grow
                # path works on the next signal.
                if downloaded < total:
                    for node in self.lst_nodes_viewer or []:
                        vtk_w = getattr(node, "vtk_widget", None)
                        if vtk_w is None or vtk_w._progressive_mode:
                            continue
                        try:
                            viewer_sn = str(
                                getattr(vtk_w.image_viewer, "metadata", {})
                                .get("series", {}).get("series_number", "")
                            )
                        except Exception:
                            viewer_sn = ""
                        if viewer_sn == sn:
                            avail = vtk_w.get_count_of_slices()
                            vtk_w.enter_progressive_mode(total, sn)
                            vtk_w.update_available_slice_count(avail)
                            info["last_grow_count"] = avail
                            self.logger.info(
                                "progressive: re-activated series=%s avail=%d (done-guard recovery)",
                                sn, avail,
                            )
                            return  # Will grow on next progress signal
                # downloaded < total but no viewer found — nothing further to do
                if downloaded < total:
                    return
                # downloaded >= total — completion signal. If progressive mode was
                # exited prematurely (e.g. stale-grow exhaustion at fewer slices),
                # fire a one-shot grow so the viewer reaches the full file count.
                for _node in self.lst_nodes_viewer or []:
                    _vtk_w = getattr(_node, "vtk_widget", None)
                    if _vtk_w is None or _vtk_w._progressive_mode:
                        continue  # skip progressive viewers — handled by normal grow path
                    try:
                        _viewer_sn = str(
                            getattr(_vtk_w.image_viewer, "metadata", {})
                            .get("series", {}).get("series_number", "")
                        )
                    except Exception:
                        _viewer_sn = ""
                    if _viewer_sn != sn:
                        continue
                    _current_count = _vtk_w.get_count_of_slices()
                    if _current_count >= downloaded:
                        continue  # already showing full count — no action needed
                    self.logger.info(
                        "progressive: done-guard completion one-shot series=%s current=%d downloaded=%d",
                        sn, _current_count, downloaded,
                    )
                    _ps_info = self._progressive_series.get(sn)
                    if _ps_info is None:
                        self._progressive_series[sn] = {
                            "total": total,
                            "last_grow_count": _current_count,
                            "last_signal_ms": 0,
                            "pending_downloaded": downloaded,
                        }
                        _h10_log_progressive_mutation(self, 'done_guard_completion_oneshot', sn, 'add_key')
                    else:
                        _ps_info["pending_downloaded"] = downloaded
                        _ps_info["total"] = total
                    _viewers_shot = self._find_progressive_viewers(sn)
                    if not _viewers_shot:
                        # Re-enter progressive mode so _grow_progressive_fast locates the viewer
                        _vtk_w.enter_progressive_mode(total, sn)
                        _vtk_w.update_available_slice_count(_current_count)
                        _viewers_shot = [(_vtk_w, _node)]
                    self._grow_progressive_fast(sn, downloaded, _viewers_shot)
                    return
                # No viewer needs a grow for this completed series — nothing to do.
                # IMPORTANT: do NOT fall through to the inflight block below; that
                # would restart _start_progressive_display for an already-done series.
                return

            if (not _allow_untargeted_first_display) and _awaiting_viewer is None and _is_progressive_untargeted_deferred(self, sn):
                return

            if not _allow_untargeted_first_display:
                if not _is_progressive_untargeted_deferred(self, sn):
                    _mark_progressive_untargeted_deferred(self, sn)
                    self.logger.info(
                        "progressive: untargeted first display deferred series=%s "
                        "downloaded=%d total=%d -- awaiting explicit viewer request",
                        sn, downloaded, total,
                    )
                return

            if not _is_progressive_start_task_inflight(self, sn):
                _mark_progressive_inflight(self, sn)
                self._start_progressive_display(
                    sn, downloaded, total,
                    target_vtk_widget=_awaiting_viewer,
                    target_node=_awaiting_node,
                )

    def _find_progressive_viewers(self, series_number: str):
        """Find all VTK widgets currently in progressive mode for a series."""
        result = []
        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None:
                continue
            if (vtk_w._progressive_mode
                    and vtk_w._progressive_series_number == str(series_number)):
                result.append((vtk_w, node))
        return result

    def _start_progressive_display(self, series_number: str, downloaded: int, total: int,
                                    target_vtk_widget=None, target_node=None):
        """Display a partially downloaded series for the first time.

        If *target_vtk_widget* / *target_node* are provided, the first batch
        is loaded directly into that specific viewer (used when the user
        drag-dropped a series that wasn't on disk yet â€” the viewer is already
        showing a spinner waiting for this series).
        """
        self.logger.info(
            "progressive: START first display series=%s downloaded=%d total=%d target_viewer=%s",
            series_number, downloaded, total,
            getattr(target_vtk_widget, 'id_vtk_widget', None) if target_vtk_widget else None,
        )
        _clear_progressive_untargeted_deferred(self, series_number)
        self._progressive_series.setdefault(series_number, {
            "total": total, "last_grow_count": 0,
        })
        _set_progressive_lifecycle_state(
            self,
            str(series_number),
            _PROGRESSIVE_STATE_AWAITING,
            source="_start_progressive_display",
            reason="initial_display_start",
        )

        # Ensure import_folder_path is set â€” during download the PatientWidget
        # may have been created before any files existed on disk.
        study_path = self._ensure_import_folder_path()
        if not study_path:
            self.logger.error(
                "progressive: cannot start series=%s â€” no valid study path",
                series_number,
            )
            _clear_progressive_inflight(self, series_number)
            return

        if target_vtk_widget is None:
            try:
                _mark_progressive_untargeted_deferred(self, series_number)
                self.logger.info(
                    "progressive: DEFERRED untargeted start series=%s downloaded=%d total=%d "
                    "-- manual-only layout policy; awaiting explicit viewer request",
                    series_number,
                    downloaded,
                    total,
                )
                _clear_progressive_inflight(self, series_number)
                return
            except Exception:
                pass

        async def _load_and_show():
            try:
                await self._async_load_and_display_series(
                    series_number,
                    progressive_total=total,
                )
                # If a specific target viewer was awaiting this series,
                # switch it to show the loaded data and hide the spinner.
                if target_vtk_widget is not None:
                    self._apply_progressive_to_target_viewer(
                        series_number, total, target_vtk_widget, target_node,
                    )
                _set_progressive_lifecycle_state(
                    self,
                    str(series_number),
                    _PROGRESSIVE_STATE_PROGRESSIVE,
                    source="_start_progressive_display",
                    reason="first_display_ready_async",
                )
                # Mark done so on_series_images_progress won't re-start
                _mark_progressive_done_guard(self, series_number)
                _h10_log_progressive_mutation(self, '_start_progressive_display', series_number, 'done_add')
            except Exception as e:
                self.logger.warning("progressive: first display failed: %s", e)
            finally:
                # Clear inflight guard so the series can be retried if needed
                _clear_progressive_inflight(self, series_number)

        try:
            loop = asyncio.get_running_loop()
            task = asyncio.create_task(_load_and_show())
            self.parent_widget._background_tasks.add(task)
            task.add_done_callback(lambda t: self.parent_widget._background_tasks.discard(t))
        except RuntimeError:
            # No running asyncio loop â€” schedule via thread + QTimer callback
            self.logger.warning(
                "progressive: no asyncio loop â€” falling back to threaded load series=%s",
                series_number,
            )
            import threading

            def _threaded_load():
                try:
                    ok = self._load_single_series_on_demand(
                        int(series_number), study_path=study_path,
                    )
                    if ok:
                        _sn_local = str(series_number)
                        _total_local = total
                        _target_vw = target_vtk_widget
                        _target_nd = target_node

                        def _display_activate_and_mark_done():
                            """Display, activate progressive mode, THEN mark done.

                            Previously done.add() ran from the background thread
                            before these callbacks fired, causing a race where
                            subsequent progress signals hit the done-guard before
                            progressive mode was entered â€” killing the grow path.

                            H6 fix (v2.2.9.3): guard against post-completion
                            re-entry.  If the series completed while the threaded
                            load was running, this callback fires AFTER the
                            completion handler cleaned up.  Without this guard,
                            enter_progressive_mode re-enters progressive state on
                            a completed series â†’ crash during scroll.
                            Also wrapped in try/except so no exception can escape
                            to Qt's C++ dispatch (H6b â€” unguarded QTimer closure).
                            """
                            try:
                                # H6 guard: skip if series already completed
                                if _is_series_download_completed(self, _sn_local):
                                    self.logger.info(
                                        "progressive: skipping late activation for "
                                        "completed series=%s", _sn_local,
                                    )
                                    return
                                # If a specific viewer was awaiting this series (drag-drop
                                # before data existed), switch that viewer directly.
                                if _target_vw is not None:
                                    self._apply_progressive_to_target_viewer(
                                        _sn_local, _total_local, _target_vw, _target_nd,
                                    )
                                else:
                                    self._display_series_after_load(
                                        _sn_local, progressive_total=_total_local,
                                    )
                                self._activate_progressive_mode_on_viewers(
                                    _sn_local, _total_local,
                                )
                                _set_progressive_lifecycle_state(
                                    self,
                                    _sn_local,
                                    _PROGRESSIVE_STATE_PROGRESSIVE,
                                    source="_start_progressive_display_threaded",
                                    reason="first_display_ready_threaded",
                                )
                                # Mark done AFTER activation so grow path is reachable
                                _mark_progressive_done_guard(self, _sn_local)
                                _h10_log_progressive_mutation(self, '_start_progressive_display_threaded', _sn_local, 'done_add')
                            except Exception as _cb_exc:
                                self.logger.error(
                                    "progressive: _display_activate_and_mark_done "
                                    "failed series=%s: %s",
                                    _sn_local, _cb_exc, exc_info=True,
                                )

                        QTimer.singleShot(0, _display_activate_and_mark_done)
                except Exception as exc:
                    self.logger.warning("progressive: threaded fallback failed: %s", exc)
                finally:
                    _clear_progressive_inflight(self, series_number)

            thread = threading.Thread(
                target=_threaded_load,
                name="progressive-load-" + str(series_number),
                daemon=True,
            )
            thread.start()

    def _flush_progressive_grow(self):
        """Timer callback: grow all progressive viewers with newly downloaded images."""
        try:
            self._flush_progressive_grow_impl()
        except Exception as exc:
            self.logger.error(
                "progressive: unhandled error in _flush_progressive_grow: %s",
                exc, exc_info=True,
            )

    def _flush_progressive_grow_impl(self):
        """Inner implementation called by _flush_progressive_grow."""
        is_fast = self._is_fast_viewer_mode()
        admit_batch = _get_progressive_admit_batch_size(self)
        now_mono_ms = float(time.perf_counter() * 1000.0)

        for sn, info in list(self._progressive_series.items()):
            pending = info.get("pending_downloaded", 0)
            last_grow = info.get("last_grow_count", 0)
            if pending <= last_grow:
                continue  # nothing new to process
            total = info.get("total", 0)
            viewers = self._find_progressive_viewers(sn)
            if not viewers:
                continue

            if is_fast:
                is_terminal = total > 0 and pending >= total
                visible_target = pending
                if not is_terminal and admit_batch > 0:
                    visible_target = min(pending, last_grow + admit_batch)
                # ── F10: defer TERMINAL grow during hot FAST drag ──────────
                # Live log (4/29/2026) showed _grow_progressive_fast taking
                # 546 ms on a terminal completion mid-drag, blocking the
                # main thread independently of F9's Layer 2b defer.
                # R4 says terminal completion fires; we honor that by
                # force-running after _FAST_PROGRESSIVE_FINALIZE_DEFER_MAX_RETRIES.
                if is_terminal and _is_fast_progressive_interaction_hot(viewers):
                    f10_map = _get_terminal_grow_defer_retry_map(self)
                    f10_retry = int(f10_map.get(sn, 0))
                    if f10_retry < _FAST_PROGRESSIVE_FINALIZE_DEFER_MAX_RETRIES:
                        f10_delay = max(
                            float(_progressive_grow_interval_ms()),
                            float(
                                _FAST_PROGRESSIVE_FINALIZE_DEFER_BASE_MS
                                + f10_retry * _FAST_PROGRESSIVE_FINALIZE_DEFER_STEP_MS
                            ),
                        )
                        f10_map[sn] = f10_retry + 1
                        info["pending_downloaded"] = pending
                        if not self._progressive_grow_timer.isActive():
                            _restart_progressive_grow_timer(self, f10_delay)
                        self.logger.info(
                            "[F10] terminal grow deferred series=%s retry=%d/%d delay_ms=%.0f "
                            "pending=%d total=%d (FAST drag active; avoids ~500ms+ main-thread freeze)",
                            sn, f10_retry + 1,
                            _FAST_PROGRESSIVE_FINALIZE_DEFER_MAX_RETRIES,
                            f10_delay, pending, total,
                        )
                        continue
                    # Retry budget exhausted — force-run to honor R4.
                    f10_map.pop(sn, None)
                    self.logger.warning(
                        "[F10] terminal grow force-running after %d defer retries series=%s "
                        "(drag still hot — accepting freeze to satisfy R4)",
                        f10_retry, sn,
                    )
                else:
                    # Clear any stale terminal-grow retry counter.
                    _get_terminal_grow_defer_retry_map(self).pop(sn, None)
                # ───────────────────────────────────────────────────────────
                if not is_terminal and _is_fast_progressive_interaction_hot(viewers):
                    info["pending_downloaded"] = pending
                    if not self._progressive_grow_timer.isActive():
                        _restart_progressive_grow_timer(
                            self,
                            max(_progressive_grow_interval_ms(), 500.0),
                        )
                    self.logger.debug(
                        "progressive-fast: interaction-hot defer series=%s pending=%d total=%d",
                        sn, pending, total,
                    )
                    continue
                if not is_terminal:
                    pending_delta = max(0, int(pending) - int(last_grow))
                    last_tick_ms = float(info.get("_last_nonterminal_grow_mono_ms", 0.0) or 0.0)
                    last_cost_ms = float(info.get("_last_nonterminal_grow_cost_ms", 0.0) or 0.0)
                    min_interval_ms = float(_FAST_PROGRESSIVE_NONTERMINAL_GROW_MIN_INTERVAL_MS)
                    if pending_delta < max(1, int(admit_batch) * 2):
                        # Small visible deltas do not need immediate expensive refresh.
                        min_interval_ms = max(min_interval_ms, 1300.0)
                    if last_cost_ms >= 250.0:
                        # If previous grow was heavy, widen the gap before next grow.
                        min_interval_ms = max(
                            min_interval_ms,
                            min(
                                float(_FAST_PROGRESSIVE_NONTERMINAL_GROW_MAX_INTERVAL_MS),
                                last_cost_ms * 2.0,
                            ),
                        )
                    if last_tick_ms > 0.0:
                        elapsed_ms = max(0.0, now_mono_ms - last_tick_ms)
                        if elapsed_ms < min_interval_ms:
                            info["pending_downloaded"] = pending
                            delay_ms = max(
                                _progressive_grow_interval_ms(),
                                min_interval_ms - elapsed_ms,
                            )
                            if not self._progressive_grow_timer.isActive():
                                _restart_progressive_grow_timer(self, delay_ms)
                            self.logger.debug(
                                "progressive-fast: nonterminal cadence defer series=%s pending=%d "
                                "last_grow=%d elapsed_ms=%.1f min_interval_ms=%.1f last_cost_ms=%.1f",
                                sn, pending, last_grow, elapsed_ms, min_interval_ms, last_cost_ms,
                            )
                            continue
                if _should_defer_progressive_grow(terminal=is_terminal):
                    info["pending_downloaded"] = pending
                    if not self._progressive_grow_timer.isActive():
                        _restart_progressive_grow_timer(self, _progressive_grow_interval_ms())
                    self.logger.debug(
                        "progressive-fast: deferred grow series=%s pending=%d total=%d",
                        sn, pending, total,
                    )
                    continue
                # Fast mode: refresh backend file list + update available count
                # (no VTK volume reconstruction needed).
                # Guard: prevent exceptions from escaping the QTimer callback.
                # One-time-per-series traceback log avoids 150ms log spam.
                try:
                    grow_cost_ms = float(self._grow_progressive_fast(
                        sn,
                        pending,
                        viewers,
                        visible_count=visible_target,
                    ) or 0.0)
                    if not is_terminal:
                        info["_last_nonterminal_grow_mono_ms"] = float(time.perf_counter() * 1000.0)
                        info["_last_nonterminal_grow_cost_ms"] = float(max(0.0, grow_cost_ms))
                    if visible_target < pending:
                        self.logger.debug(
                            "progressive-fast: admission gate series=%s visible=%d pending=%d total=%d batch=%d",
                            sn,
                            visible_target,
                            pending,
                            total,
                            admit_batch,
                        )
                    # Clear flags on success so a future re-occurrence is fully logged
                    info.pop("_grow_error_logged", None)
                    info.pop("_grow_error_count", None)
                except Exception as exc:
                    err_count = info.get("_grow_error_count", 0) + 1
                    info["_grow_error_count"] = err_count
                    _GROW_ERROR_MAX = 5
                    if not info.get("_grow_error_logged"):
                        info["_grow_error_logged"] = True
                        self.logger.error(
                            "progressive: _grow_progressive_fast failed series=%s: %s",
                            sn, exc, exc_info=True,
                        )
                    else:
                        self.logger.warning(
                            "progressive: _grow_progressive_fast still failing series=%s (%d/%d): %s",
                            sn, err_count, _GROW_ERROR_MAX, exc,
                        )
                    if err_count >= _GROW_ERROR_MAX:
                        # Bounded retry: after N consecutive failures, equalize
                        # pending to last_grow_count so the safety-net below
                        # does NOT re-arm the timer.  Prevents infinite storm.
                        info["pending_downloaded"] = info.get("last_grow_count", 0)
                        self.logger.error(
                            "progressive: grow retry exhausted series=%s after %d failures, "
                            "stopping timer re-arm",
                            sn, err_count,
                        )
            else:
                # Advanced (VTK) mode: reload from disk + grow VTK volume in-place
                async def _grow(series_number=sn, count=pending):
                    try:
                        await self._grow_progressive_viewer_async(series_number, count)
                    except Exception as e:
                        self.logger.warning("progressive: grow failed series=%s: %s", series_number, e)

                try:
                    loop = asyncio.get_running_loop()
                    task = asyncio.create_task(_grow())
                    self.parent_widget._background_tasks.add(task)
                    task.add_done_callback(lambda t: self.parent_widget._background_tasks.discard(t))
                except RuntimeError:
                    pass

        # Stale-grow safety net: restart the single-shot timer if any tracked
        # series still has pending_downloaded > last_grow_count after this
        # tick.  Prevents permanent "stuck" state when loader.grow() returned
        # a stale file count (OS flush delay) and closed the timer.
        if any(
            info.get("pending_downloaded", 0) > info.get("last_grow_count", 0)
            for info in self._progressive_series.values()
        ):
            if not self._progressive_grow_timer.isActive():
                _restart_progressive_grow_timer(self, _progressive_grow_interval_ms())

    def _dispatch_post_completion_cache_warm(
        self,
        series_number: str,
        viewers: list,
        *,
        _retry: int = 0,
    ) -> None:
        """Defer post-completion cache warm while protected UI is active."""
        if (_should_defer_cache_warm() or not _should_admit_cache_warm(self, series_number)) and _retry < 3:
            self.logger.debug(
                "progressive-fast: cache-warm deferred series=%s retry=%d",
                series_number, _retry + 1,
            )
            QTimer.singleShot(
                750,
                lambda sn=str(series_number), vs=viewers, retry=_retry + 1:
                    self._dispatch_post_completion_cache_warm(sn, vs, _retry=retry),
            )
            return

        for vtk_w, node in viewers:
            try:
                bridge = getattr(vtk_w, "image_viewer", None)
                pipeline = getattr(bridge, "pipeline", None)
                if pipeline is not None and hasattr(pipeline, "_prefetch_around"):
                    current_slice = getattr(bridge, "_current_slice", 0)
                    # Reset dedup so prefetch runs even if same position
                    pipeline._last_prefetch_center = -1
                    pipeline._prefetch_around(current_slice, direction=0)
                    self.logger.info(
                        "progressive-fast: series=%s cache-warm dispatched around slice=%d",
                        series_number, current_slice,
                    )
            except Exception as _cw_exc:
                self.logger.debug(
                    "progressive-fast: cache-warm failed series=%s: %s",
                    series_number, _cw_exc,
                )

    def _finalize_progressive_series(
        self,
        series_number: str,
        *,
        final_count: int = 0,
        viewers: list | None = None,
        source: str,
        dispatch_cache_warm: bool = False,
    ) -> bool:
        return _finalize_progressive_series(
            self,
            series_number,
            final_count=final_count,
            viewers=viewers,
            source=source,
            dispatch_cache_warm=dispatch_cache_warm,
        )

    def _grow_progressive_fast(
        self,
        series_number: str,
        pending_count: int,
        viewers: list,
        *,
        visible_count: int | None = None,
    ):
        """Fast mode growth: refresh PyDicom backend file list & update counts.

        Unlike the VTK path, no volume reconstruction is needed.  The PyDicom
        lazy backend already serves slices on-demand from disk.  We only need
        to tell it about new files so ``get_slice_count()`` returns the correct
        value, and update the ImageSliceBooster paths if the series is active.

        ``pending_count`` tracks how many slices the downloader says are already
        on disk.  ``visible_count`` optionally caps how many of those slices are
        admitted into the viewer this tick; this is the viewer-side burst gate
        used while a series is still actively downloading.

        Also updates lst_thumbnails_data metadata so that re-dropping the series
        into another viewer will see the full file count (fixes stuck-slice bug).
        """
        info = self._progressive_series.get(series_number, {})
        total = info.get("total", 0)
        _t_grow = now_ms()
        target_visible_count = max(
            0,
            min(
                int(pending_count),
                int(pending_count if visible_count is None else visible_count),
            ),
        )
        _set_progressive_lifecycle_state(
            self,
            series_number,
            _PROGRESSIVE_STATE_PROGRESSIVE,
            source="_grow_progressive_fast",
            reason="grow_tick",
        )

        for vtk_w, node in viewers:
            new_count = pending_count  # fallback
            try:
                # 1. Refresh the PyDicom backend file list + grow lazy volume.
                #
                # IMPORTANT: call loader.grow() FIRST without pre-calling
                # backend.refresh_file_list() separately.  grow() snapshots
                # old_paths BEFORE refreshing, so it can correctly build the
                # old-index â†’ new-index remap for interleaved DICOM series.
                # Pre-calling refresh_file_list() here poisons that snapshot,
                # causing decoded pixels to land at wrong memmap positions when
                # instance numbers interleave across download batches.
                loader = getattr(vtk_w, "_lazy_loader", None)
                backend = getattr(loader, "backend", None) if loader is not None else None
                if loader is not None and hasattr(loader, "grow"):
                    # PyDicom lazy backend: grow() handles refresh + remap internally
                    try:
                        new_count = loader.grow()
                    except Exception as grow_exc:
                        self.logger.error(
                            "progressive-fast: loader.grow() failed series=%s: %s",
                            series_number, grow_exc,
                        )
                        raise
                    # v2.2.8.2: After grow(), the lazy volume's vtk_image_data now has
                    # new_count slices, but ImageReslice.SetOutputExtent() was set at
                    # construction time with the original (smaller) Z extent.  VTK's
                    # vtkResliceImageViewer clamps SetSlice(n) to the output extent max,
                    # so slices >= old_count are silently rendered as old_count-1.
                    # Fix: re-derive the output extent from the updated input dimensions.
                    # If preprocessing (e.g. CT XY-upsample) created a different object,
                    # reconnect reslice input to loader.vtk_image_data which has all slices.
                    try:
                        _iv = getattr(vtk_w, "image_viewer", None)
                        _reslice = getattr(_iv, "image_reslice", None) if _iv is not None else None
                        if _reslice is not None:
                            _raw_vtkdata = getattr(loader, "vtk_image_data", None)
                            _reslice_input = getattr(_reslice, "vtk_image_data", None)
                            if (_raw_vtkdata is not None and _reslice_input is not None
                                    and _reslice_input is not _raw_vtkdata):
                                # Preprocessing created a separate copy (e.g. CT upsample).
                                # Reconnect so the new slices in loader.vtk_image_data are
                                # reachable by the reslice pipeline.
                                _reslice.SetInputData(_raw_vtkdata)
                                _reslice.vtk_image_data = _raw_vtkdata
                            # Update output extent from current input dimensions (new_count).
                            if hasattr(_reslice, "_configure_output_from_input"):
                                _reslice._configure_output_from_input()
                            _reslice.Modified()
                            _reslice.Update()
                    except Exception as _reslice_exc:
                        self.logger.debug(
                            "progressive-fast: reslice extent update failed: %s", _reslice_exc
                        )
                elif backend is not None and hasattr(backend, "refresh_file_list"):
                    # Lazy loader without grow() â€“ fallback to direct backend refresh
                    new_count = backend.refresh_file_list()
                    if loader is not None and hasattr(loader, "slice_count"):
                        loader.slice_count = new_count
                elif getattr(vtk_w, "_qt_bridge_active", False):
                    # Qt bridge (PYDICOM_QT): grow the pipeline's file list so
                    # _slice_count on the bridge stays in sync with downloaded
                    # files.  Without this the bridge clamps set_slice() to the
                    # original batch size and the image appears "stuck".
                    bridge = getattr(vtk_w, "image_viewer", None)
                    if bridge is not None and hasattr(bridge, "grow"):
                        new_count = bridge.grow()
            except Exception as exc:
                self.logger.debug("progressive-fast: refresh_file_list/grow failed: %s", exc)

            admitted_count = min(new_count, target_visible_count)

            # 2+3. Update slice count and slider max
            self._update_vtk_slice_range(
                vtk_w,
                node,
                new_count,
                available_count=admitted_count,
            )

            # 4. Update ImageSliceBooster paths if active for this series
            try:
                loader = getattr(vtk_w, "_lazy_loader", None)
                backend = getattr(loader, "backend", None) if loader is not None else None
                if backend is not None:
                    updated_paths = backend.get_file_paths()
                else:
                    updated_paths = []
                if updated_paths and self._image_slice_booster.active_series == series_number:
                    self._image_slice_booster.update_paths(series_number, updated_paths)
            except Exception as exc:
                self.logger.debug("progressive-fast: booster update_paths failed: %s", exc)

        # 5+6. Update stored metadata and sync to live viewers
        self._refresh_and_sync_metadata(series_number, new_count)

        info["last_grow_count"] = admitted_count
        self.logger.info(
            "progressive-fast: grew series=%s visible=%d actual=%d/%d",
            series_number, admitted_count, new_count, total,
        )
        log_stage_timing(
            self.logger,
            component="viewer",
            function="ViewerController._grow_progressive_fast",
            stage="progressive_grow_apply",
            start_ms=_t_grow,
            series=str(series_number),
            admitted=admitted_count,
            actual=new_count,
            total=total,
        )
        grow_total_ms = float(now_ms() - _t_grow)

        # â”€â”€ Stale-grow guard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # loader.grow() may return fewer slices than expected if the OS has
        # not yet flushed all downloaded files to disk.  The single-shot
        # timer will not fire again on its own, so we must reschedule it.
        # Also handles the one-shot path where the viewer is not in
        # progressive mode â€” enter_progressive_mode() lets
        # _find_progressive_viewers() locate the viewer on the retry tick.
        # MAX = 5 retries (أ—150ms = 750ms window).  On exhaustion: accept
        # best-effort count, stop safety-net loop, exit progressive mode.
        # The done-guard completion one-shot will recover when DM sends the
        # final signal (after the OS has certainly flushed).
        _STALE_RETRY_MAX = 5
        if new_count < target_visible_count:
            _stale_retry = info.get("_stale_retry_count", 0)
            if _stale_retry < _STALE_RETRY_MAX:
                info["_stale_retry_count"] = _stale_retry + 1
                # Keep pending_downloaded set so _flush_progressive_grow retries
                info["pending_downloaded"] = pending_count
                # Enter progressive mode on non-progressive viewers (one-shot path)
                # so _find_progressive_viewers() can locate them on the retry tick
                for _vtk_w2, _ in viewers:
                    if not _vtk_w2._progressive_mode:
                        _vtk_w2.enter_progressive_mode(total, series_number)
                        _vtk_w2.update_available_slice_count(new_count)
                if not self._progressive_grow_timer.isActive():
                    _restart_progressive_grow_timer(self, _progressive_grow_interval_ms())
                self.logger.warning(
                    "progressive-fast: STALE grow series=%s got=%d expected=%d "
                    "(retry %d/%d in %dms)",
                    series_number, new_count, target_visible_count,
                    info["_stale_retry_count"], _STALE_RETRY_MAX,
                    self._progressive_grow_timer.interval(),
                )
            else:
                # Max retries exhausted â€” OS buffer not flushing in time.
                # Accept best-effort count: equalise pending to stop the
                # _flush_progressive_grow safety-net from looping, then
                # exit progressive mode so the viewer is usable at whatever
                # count is available.  The done-guard completion one-shot
                # will recover the remaining images when DM sends the final
                # completion signal.
                self.logger.error(
                    "progressive-fast: STALE-EXHAUSTED series=%s stuck at %d/%d after %d retries"
                    " â€” exiting progressive mode; done-guard will recover on completion signal",
                    series_number, new_count, target_visible_count, _stale_retry,
                )
                _set_progressive_lifecycle_state(
                    self,
                    series_number,
                    _PROGRESSIVE_STATE_COMPLETING,
                    source="_grow_progressive_fast",
                    reason="stale_exhausted_waiting_completion_signal",
                )
                info["pending_downloaded"] = new_count  # stop safety-net loop
                self._progressive_series.pop(series_number, None)
                _h10_log_progressive_mutation(self, '_grow_progressive_fast', series_number, 'pop_stale_exhausted')
                for _vtk_w2, _n2 in viewers:
                    _sl2 = getattr(_n2, "slider", None)
                    if _sl2 is not None:
                        try:
                            _sl2.blockSignals(True)
                            _sl2.setMaximum(max(0, new_count - 1))
                            _sl2.blockSignals(False)
                        except Exception:
                            pass
                    try:
                        _vtk_w2.exit_progressive_mode()
                    except Exception as _epm_exc:
                        self.logger.warning(
                            "progressive-fast: exit_progressive_mode failed "
                            "viewer_id=%s series=%s (stale-exhausted): %s",
                            getattr(_vtk_w2, "id_vtk_widget", id(_vtk_w2)),
                            series_number, _epm_exc,
                        )
                    # Refresh corner text after exiting progressive mode
                    try:
                        _iv = getattr(_vtk_w2, "image_viewer", None)
                        if _iv is not None and hasattr(_iv, "update_corners_actors"):
                            _iv.update_corners_actors()
                    except Exception:
                        pass
                self._update_thumbnail_count(series_number, new_count)
                return grow_total_ms
                return  # don't fall through to step 6 (already cleaned up)

        # 6. Check if download completed
        completion_snapshot = build_series_completeness_snapshot(
            series_number,
            expected_count=total,
            disk_count=new_count,
            viewer_visible_count=admitted_count,
        )
        if total > 0 and completion_snapshot.is_viewer_complete:
            if _finalize_progressive_series(
                self,
                series_number,
                final_count=new_count,
                viewers=viewers,
                source="grow_complete",
                dispatch_cache_warm=True,
            ):
                self.logger.info(
                    "progressive-fast: series=%s COMPLETE (%d slices)", series_number, new_count
                )
        return grow_total_ms

    async def _grow_progressive_viewer_async(self, series_number: str, expected_count: int):
        """Background: reload partial series from disk and grow viewers in-place."""
        study_path = self._get_correct_study_path()
        if not study_path:
            return

        # Load whatever files exist on disk (runs in executor to avoid blocking UI)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._load_partial_series_from_disk(series_number, study_path),
        )
        if result is None:
            return

        new_vtk_data, new_metadata = result
        new_dims = new_vtk_data.GetDimensions() if new_vtk_data else (0, 0, 0)
        new_z = int(new_dims[2]) if new_dims and len(new_dims) > 2 else 0

        if new_z <= 0:
            return

        # Apply growth on UI thread
        info = self._progressive_series.get(series_number, {})
        info["last_grow_count"] = new_z

        viewers = self._find_progressive_viewers(series_number)
        for vtk_w, node in viewers:
            try:
                grew = vtk_w.grow_progressive_series(new_vtk_data, new_metadata)
                if grew:
                    self.logger.info(
                        "progressive: grew series=%s slices=%d", series_number, new_z
                    )
                    # Also update the data in lst_thumbnails_data for consistency
                    self._apply_loaded_series_data(
                        series_number, new_vtk_data, new_metadata,
                        patient_pk=None, study_pk=None,
                        refresh_viewer=False,
                    )
            except Exception as e:
                self.logger.warning("progressive: grow viewer failed: %s", e)

        # If we reached total, exit progressive mode
        total = info.get("total", 0)
        if new_z >= total and total > 0:
            # Refresh stored metadata + invalidate stale caches
            self._refresh_and_sync_metadata(series_number, new_z)
            self._invalidate_series_caches(series_number)
            for vtk_w, node in viewers:
                vtk_w.exit_progressive_mode()
            self._progressive_series.pop(series_number, None)
            _h10_log_progressive_mutation(self, '_grow_progressive_fast', series_number, 'pop_total_reached')
            self.logger.info("progressive: series=%s COMPLETE (%d slices)", series_number, new_z)

    def _load_partial_series_from_disk(self, series_number: str, study_path: str):
        """Load whatever DICOM files currently exist on disk for a series.

        This is called from a background executor thread.
        Returns (vtk_image_data, metadata) or None.
        """
        try:
            from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number
            result = load_single_series_by_number(
                study_path=study_path,
                series_number=series_number,
                patient_pk=getattr(self.parent_widget, 'patient_pk', None),
                study_pk=getattr(self.parent_widget, 'study_pk', None),
                allow_lazy_backend=False,  # Force VTK backend for partial loading
            )
            if result is None:
                return None
            # load_single_series_by_number is a generator yielding
            # (vtk_image_data, metadata, ...)
            for item in result:
                if item and len(item) >= 2:
                    return (item[0], item[1])
            return None
        except Exception as e:
            self.logger.warning("progressive: partial load failed series=%s: %s", series_number, e)
            return None

    def on_series_download_fully_complete(self, series_number: str):
        """Qt signal slot: outer guard so exceptions never escape into Qt dispatch."""
        try:
            self._on_series_download_fully_complete_impl(series_number)
        except Exception as exc:
            self.logger.error(
                "progressive: unhandled error in on_series_download_fully_complete "
                "series=%s: %s",
                series_number, exc, exc_info=True,
            )

    def _on_series_download_fully_complete_impl(self, series_number: str):
        """Called when a series finishes downloading completely.

        Performs a FINAL grow on all viewers showing this series to ensure
        every downloaded file is visible, then exits progressive mode.
        Also refreshes corner text ("X / Y") and thumbnail image count.
        Schedules a deferred verification (500ms) to catch OS-flush-delayed
        files that were not yet visible at the time of this call.

        v2.2.9.2 â€” only exits progressive mode if grow got all expected files.
        If the OS hasn't flushed the last batch yet, Layer 3 / Layer 4 handle
        the remaining images while progressive mode stays active.
        """
        sn = str(series_number)
        if _is_progressive_finalized(self, sn):
            self.logger.debug(
                "progressive: Layer 2b skipped finalized series=%s", sn,
            )
            return

        # ── F9: defer Layer 2b body during active FAST drag ──────────────
        # Live log evidence (4/29/2026) showed the entire body of this
        # method (`loader.grow()` × N viewers + `_update_vtk_slice_range`
        # + completion-snapshot computation + `_invalidate_series_caches`
        # + ZetaBoost lazy-volume promotion) blocks the main thread for
        # 700–1750 ms when a series finishes downloading WHILE the user
        # is actively stack-dragging. R4 says "terminal completion always
        # fires" — but a 1.7 s freeze defeats responsiveness more than a
        # 350 ms delay does. We defer with bounded retry; after
        # _FAST_PROGRESSIVE_FINALIZE_DEFER_MAX_RETRIES we force-run to
        # satisfy R4 even if drag is still hot.
        try:
            f9_matched = _match_viewers_for_series(self, sn)
            if f9_matched and _is_fast_progressive_interaction_hot(f9_matched):
                pending = _get_layer2b_defer_pending_set(self)
                retry_map = _get_layer2b_defer_retry_map(self)
                retry = int(retry_map.get(sn, 0))
                if sn in pending:
                    # Already a retry in flight; new caller is duplicate.
                    self.logger.debug(
                        "[F9] Layer 2b duplicate during defer skipped series=%s retry=%d",
                        sn, retry,
                    )
                    return
                if retry < _FAST_PROGRESSIVE_FINALIZE_DEFER_MAX_RETRIES:
                    delay_ms = int(
                        _FAST_PROGRESSIVE_FINALIZE_DEFER_BASE_MS
                        + retry * _FAST_PROGRESSIVE_FINALIZE_DEFER_STEP_MS
                    )
                    pending.add(sn)
                    retry_map[sn] = retry + 1
                    self.logger.info(
                        "[F9] Layer 2b deferred series=%s retry=%d/%d delay_ms=%d "
                        "(FAST drag active; avoids ~1s+ main-thread freeze)",
                        sn, retry + 1,
                        _FAST_PROGRESSIVE_FINALIZE_DEFER_MAX_RETRIES,
                        delay_ms,
                    )

                    def _f9_retry(_sn=sn):
                        try:
                            _get_layer2b_defer_pending_set(self).discard(_sn)
                        except Exception:
                            pass
                        try:
                            self._on_series_download_fully_complete_impl(_sn)
                        except Exception as _exc:
                            self.logger.debug(
                                "[F9] Layer 2b retry failed series=%s: %s",
                                _sn, _exc,
                            )

                    QTimer.singleShot(delay_ms, _f9_retry)
                    return
                # Retry budget exhausted — force-run to honor R4.
                pending.discard(sn)
                retry_map.pop(sn, None)
                self.logger.warning(
                    "[F9] Layer 2b force-running after %d defer retries series=%s "
                    "(drag still hot — accepting freeze to satisfy R4)",
                    retry, sn,
                )
            else:
                # Not hot — clear any stale retry counter.
                _get_layer2b_defer_retry_map(self).pop(sn, None)
        except Exception as _f9_exc:
            self.logger.debug(
                "[F9] defer gate raised series=%s — falling through: %s",
                sn, _f9_exc,
            )
        # ──────────────────────────────────────────────────────────────────

        _set_progressive_lifecycle_state(
            self,
            sn,
            _PROGRESSIVE_STATE_COMPLETING,
            source="_on_series_download_fully_complete_impl",
            reason="definitive_completion_signal",
        )

        # B3.8d: Duplicate call guard — prevents double execution for the
        # same series within a short window (caused by both series_downloaded
        # and completion pulse arriving for the same series).
        if _is_layer2b_complete_guard_active(self, sn):
            self.logger.debug(
                "progressive: Layer 2b duplicate call skipped series=%s", sn,
            )
            return
        _mark_layer2b_complete_guard(self, sn)

        info = self._progressive_series.get(sn, {})
        expected_total = info.get("total", 0)
        final_count = 0
        all_viewers_complete = True
        matched_viewers = []

        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None:
                continue
            # Match by progressive series number OR by displayed series metadata
            is_match = (vtk_w._progressive_series_number == sn)
            if not is_match:
                try:
                    viewer_sn = str(
                        getattr(vtk_w.image_viewer, "metadata", {})
                        .get("series", {}).get("series_number", "")
                    )
                    is_match = (viewer_sn == sn)
                except Exception:
                    pass
            if not is_match:
                continue
            matched_viewers.append((vtk_w, node))

            # Final grow: pick up any remaining files before exiting progressive.
            # B3.8b: Added Qt bridge and backend fallback paths to match
            # _grow_progressive_fast's 3-tier priority (lazy_loader → backend → bridge).
            try:
                loader = getattr(vtk_w, "_lazy_loader", None)
                if loader is not None and hasattr(loader, "grow"):
                    new_count = loader.grow()
                    final_count = max(final_count, new_count)
                    self._update_vtk_slice_range(vtk_w, node, new_count)
                    self.logger.info(
                        "progressive: final grow on download-complete series=%s count=%d",
                        sn, new_count,
                    )
                else:
                    # B3.8b: FAST/pydicom_qt viewers don't have _lazy_loader.grow().
                    # Try backend.refresh_file_list() or Qt bridge.grow() instead.
                    backend = getattr(loader, "backend", None) if loader is not None else None
                    if backend is not None and hasattr(backend, "refresh_file_list"):
                        new_count = backend.refresh_file_list()
                        final_count = max(final_count, new_count)
                        self._update_vtk_slice_range(vtk_w, node, new_count)
                        self.logger.info(
                            "progressive: final grow (backend) on download-complete series=%s count=%d",
                            sn, new_count,
                        )
                    elif getattr(vtk_w, "_qt_bridge_active", False):
                        bridge = getattr(vtk_w, "image_viewer", None)
                        if bridge is not None and hasattr(bridge, "grow"):
                            new_count = bridge.grow()
                            final_count = max(final_count, new_count)
                            self._update_vtk_slice_range(vtk_w, node, new_count)
                            self.logger.info(
                                "progressive: final grow (qt_bridge) on download-complete series=%s count=%d",
                                sn, new_count,
                            )
            except Exception as exc:
                self.logger.debug(
                    "progressive: final grow failed series=%s: %s", sn, exc
                )

            # v2.2.9.2 â€” only exit progressive if all expected files arrived.
            # If the OS hasn't flushed the last batch, keep progressive mode
            # so that Layer 3 (500ms verify) can pick up the remaining files.
            completion_snapshot = build_series_completeness_snapshot(
                sn,
                expected_count=expected_total,
                disk_count=final_count,
            )
            if completion_snapshot.is_incomplete:
                all_viewers_complete = False
                self.logger.info(
                    "progressive: download-complete but grow incomplete series=%s "
                    "count=%d expected=%d â€” keeping progressive mode for Layer 3",
                    sn, final_count, expected_total,
                )

        # v2.2.9.2 â€” only pop tracking info if all viewers got all files.
        # Layer 3 / Layer 4 need the info to keep growing.
        finalized = False
        if all_viewers_complete:
            _finalize_progressive_series(
                self,
                sn,
                final_count=final_count,
                viewers=matched_viewers,
                source='layer2b_complete',
            )
            finalized = True

        # Update stored metadata so re-drop and thumbnails use the final count
        if final_count > 0 and not finalized:
            self._refresh_and_sync_metadata(sn, final_count)
            self._invalidate_series_caches(sn)

        # FAST mode: promote completed lazy volume to ZetaBoost so re-visits
        # get an O(1) cache hit instead of re-decoding all slices from disk.
        # Must run AFTER _invalidate_series_caches (which clears stale entries)
        # and AFTER the final grow (which ensures all slices are decoded).
        if all_viewers_complete and final_count > 0 and self._is_fast_viewer_mode():
            for node in self.lst_nodes_viewer or []:
                vtk_w = getattr(node, "vtk_widget", None)
                if vtk_w is None:
                    continue
                loader = getattr(vtk_w, "_lazy_loader", None)
                if loader is None or not hasattr(loader, "vtk_image_data"):
                    continue
                try:
                    viewer_sn = str(
                        getattr(vtk_w.image_viewer, "metadata", {})
                        .get("series", {}).get("series_number", "")
                    )
                    if viewer_sn != sn:
                        continue
                    vtk_data = loader.vtk_image_data
                    meta = getattr(vtk_w.image_viewer, "metadata", None)
                    if vtk_data is not None and isinstance(meta, dict):
                        self._full_cache_put(sn, vtk_data, meta)
                        self.logger.info(
                            "progressive: promoted FAST lazy volume to ZetaBoost "
                            "series=%s slices=%d", sn, final_count,
                        )
                        break  # one promotion per series is enough
                except Exception as exc:
                    self.logger.debug(
                        "progressive: ZetaBoost promotion failed series=%s: %s",
                        sn, exc,
                    )

        # Update thumbnail label to show the definitive image count
        if final_count > 0 and not finalized:
            self._update_thumbnail_count(sn, final_count)

        # v2.2.9.2 — invalidate disk count cache so Layer 3 gets a fresh read.
        self._invalidate_disk_count_cache(sn)

        # Schedule deferred verification to catch OS-flush-delayed files.
        # Expected total comes from DICOM headers (set by DM progress signals).
        if expected_total > 0:
            QTimer.singleShot(
                500,
                lambda _sn=sn, _total=expected_total: self._completion_verify_series(_sn, _total),
            )
            # Also register for Layer 4 sweep in case Layer 3 retries exhaust
            self._completion_sweep_register(sn, expected_total)

    def _update_thumbnail_count(self, series_number: str, count: int):
        """Update the thumbnail image count label (blue text) for a series.

        Falls back gracefully if thumbnail_manager is unavailable.  Uses the
        disk file count if *count* is 0 (caller didn't have a final grow count).
        """
        sn = str(series_number)
        if count <= 0:
            try:
                count = self._count_series_files_on_disk(sn)
            except Exception:
                return
        if count <= 0:
            return
        try:
            tm = getattr(self.parent_widget, "thumbnail_manager", None)
            if tm is not None and hasattr(tm, "update_series_image_count"):
                tm.update_series_image_count(sn, count)
        except Exception:
            pass

    def _refresh_corner_text(self, series_number: str):
        """Refresh 'Slice: X / Y' corner text on all viewers showing *series_number*."""
        sn = str(series_number)
        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None:
                continue
            try:
                viewer_sn = str(
                    getattr(vtk_w.image_viewer, "metadata", {})
                    .get("series", {}).get("series_number", "")
                )
            except Exception:
                viewer_sn = ""
            if viewer_sn != sn:
                continue
            try:
                iv = getattr(vtk_w, "image_viewer", None)
                if iv is not None and hasattr(iv, "update_corners_actors"):
                    iv.update_corners_actors()
            except Exception:
                pass

    # â”€â”€ Layer 3: Deferred completion verification â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _COMPLETION_VERIFY_MAX_RETRIES = 3
    _COMPLETION_VERIFY_INTERVAL_MS = 500

    def _completion_verify_series(self, series_number: str, expected_total: int,
                                  _retry: int = 0):
        """QTimer.singleShot callback: outer guard so exceptions never propagate. (v2.2.9.3)"""
        try:
            self._completion_verify_series_impl(series_number, expected_total, _retry)
        except Exception as exc:
            self.logger.error(
                "progressive: unhandled exception in _completion_verify_series "
                "series=%s retry=%d: %s",
                series_number, _retry, exc, exc_info=True,
            )

    def _completion_verify_series_impl(self, series_number: str, expected_total: int,
                                       _retry: int = 0):
        """Deferred verification: ensure viewer shows all downloaded files.

        Called 500ms after on_series_download_fully_complete.  If the viewer
        still shows fewer slices than files on disk (OS flush delay), does
        one more loader.grow() + slider update and retries up to 3 times.

        v2.2.9.2 — invalidates disk count cache before checking to avoid
        stale 1s-TTL values.  Also exits progressive mode and cleans up
        tracking info when grow succeeds (Layer 2b may have left them active).
        """
        sn = str(series_number)
        _t_verify = now_ms()
        if _is_progressive_finalized(self, sn):
            self.logger.debug(
                "completion-verify: series=%s SKIPPED -- already finalized",
                sn,
            )
            return

        # Epoch-aware guard (v2.3.5): skip redundant Layer 3 verification when
        # Layer 2b already succeeded.  Uses cached disk count (no invalidation)
        # to avoid main-thread I/O.  Falls through if viewer is behind.
        current_state = _get_progressive_lifecycle_state(self, sn)
        if current_state == _PROGRESSIVE_STATE_DONE and _is_series_download_completed(self, sn):
            try:
                cached_disk = self._count_series_files_on_disk(sn)  # 1s TTL cache
                if cached_disk > 0:
                    all_ok = True
                    for node in self.lst_nodes_viewer or []:
                        vtk_w = getattr(node, "vtk_widget", None)
                        if vtk_w is None:
                            continue
                        try:
                            viewer_sn = str(
                                getattr(vtk_w.image_viewer, "metadata", {})
                                .get("series", {}).get("series_number", "")
                            )
                        except Exception:
                            viewer_sn = ""
                        if viewer_sn != sn:
                            continue
                        viewer_snapshot = build_series_completeness_snapshot(
                            sn,
                            expected_count=cached_disk,
                            viewer_visible_count=vtk_w.get_count_of_slices(),
                        )
                        if not viewer_snapshot.is_viewer_complete:
                            all_ok = False
                            break
                    if all_ok:
                        self.logger.debug(
                            "completion-verify: series=%s SKIPPED -- already DONE "
                            "(viewer up-to-date, cached_disk=%d, retry=%d)",
                            sn, cached_disk, _retry,
                        )
                        return
            except Exception:
                pass  # fall through to full verification

        _set_progressive_lifecycle_state(
            self,
            sn,
            _PROGRESSIVE_STATE_COMPLETING,
            source="_completion_verify_series_impl",
            reason=f"layer3_retry_{_retry}",
        )
        # v2.2.9.2 — invalidate cache for fresh disk count
        self._invalidate_disk_count_cache(sn)
        try:
            disk_count = self._count_series_files_on_disk(sn)
        except Exception:
            disk_count = 0

        if disk_count <= 0:
            return  # no files at all â€” nothing to verify

        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None:
                continue
            try:
                viewer_sn = str(
                    getattr(vtk_w.image_viewer, "metadata", {})
                    .get("series", {}).get("series_number", "")
                )
            except Exception:
                viewer_sn = ""
            if viewer_sn != sn:
                continue

            current_count = vtk_w.get_count_of_slices()
            viewer_snapshot = build_series_completeness_snapshot(
                sn,
                expected_count=disk_count,
                viewer_visible_count=current_count,
            )
            if viewer_snapshot.is_viewer_complete:
                self.logger.debug(
                    "completion-verify: series=%s OK (viewer=%d disk=%d)",
                    sn, current_count, disk_count,
                )
                return  # viewer is up to date

            # Viewer is behind â€” do a catch-up grow
            self.logger.info(
                "completion-verify: series=%s viewer=%d < disk=%d â€” growing (retry %d/%d)",
                sn, current_count, disk_count, _retry + 1,
                self._COMPLETION_VERIFY_MAX_RETRIES,
            )
            try:
                loader = getattr(vtk_w, "_lazy_loader", None)
                if loader is not None and hasattr(loader, "grow"):
                    new_count = loader.grow()
                    self._update_vtk_slice_range(vtk_w, node, new_count)
                    self._refresh_and_sync_metadata(sn, new_count)
                    self.logger.info(
                        "completion-verify: series=%s grew to %d", sn, new_count,
                    )
                    grown_snapshot = build_series_completeness_snapshot(
                        sn,
                        expected_count=disk_count,
                        disk_count=disk_count,
                        viewer_visible_count=new_count,
                    )
                    if grown_snapshot.is_viewer_complete:
                        _finalize_progressive_series(
                            self,
                            sn,
                            final_count=new_count,
                            viewers=[(vtk_w, node)],
                            source='layer3_verify',
                        )
                        log_stage_timing(
                            self.logger,
                            component="viewer",
                            function="ViewerController._completion_verify_series_impl",
                            stage="completion_verify",
                            start_ms=_t_verify,
                            series=sn,
                            result="grew_ok",
                            retry=_retry,
                            disk_count=disk_count,
                            new_count=new_count,
                        )
                        return  # success
            except Exception as exc:
                self.logger.debug(
                    "completion-verify: grow failed series=%s: %s", sn, exc,
                )

            # Still behind â€” retry if allowed
            if _retry < self._COMPLETION_VERIFY_MAX_RETRIES - 1:
                QTimer.singleShot(
                    self._COMPLETION_VERIFY_INTERVAL_MS,
                    lambda _sn=sn, _t=expected_total, _r=_retry + 1:
                        self._completion_verify_series(_sn, _t, _r),
                )
            else:
                self.logger.warning(
                    "completion-verify: EXHAUSTED series=%s viewer still at %d vs disk=%d"
                    " after %d retries",
                    sn, vtk_w.get_count_of_slices(), disk_count,
                    self._COMPLETION_VERIFY_MAX_RETRIES,
                )
            return  # handled first matching viewer

    # â”€â”€ Layer 4: Completion sweep safety-net â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _completion_sweep_register(self, series_number: str, expected_total: int):
        """Register a series for periodic completion sweep verification."""
        self._completion_sweep_series_set.add((series_number, expected_total))
        if not self._completion_sweep_timer.isActive():
            self._completion_sweep_timer.start()

    def _completion_sweep_tick(self):
        """QTimer callback: outer guard so exceptions never escape into Qt dispatch."""
        try:
            self._completion_sweep_tick_impl()
        except Exception as exc:  # pragma: no cover
            self.logger.error(
                "progressive: unhandled error in _completion_sweep_tick: %s",
                exc, exc_info=True,
            )

    def _completion_sweep_tick_impl(self):
        """Periodic safety net: check all registered series for stale display.

        Runs every 3 seconds while there are series to verify.  For each
        series, compares viewer slice count against disk file count and
        triggers a catch-up grow if the viewer is behind.  Removes series
        from tracking once the viewer matches disk count or no viewer is
        showing it anymore.
        """
        resolved = set()
        for sn, expected_total in list(self._completion_sweep_series_set):
            if _is_progressive_finalized(self, sn):
                resolved.add((sn, expected_total))
                continue
            _set_progressive_lifecycle_state(
                self,
                sn,
                _PROGRESSIVE_STATE_COMPLETING,
                source="_completion_sweep_tick_impl",
                reason="layer4_sweep",
            )
            # v2.2.9.2 — invalidate cache for fresh disk count
            self._invalidate_disk_count_cache(sn)
            try:
                disk_count = self._count_series_files_on_disk(sn)
            except Exception:
                disk_count = 0

            if disk_count <= 0:
                resolved.add((sn, expected_total))
                continue

            _found_viewer = False
            for node in self.lst_nodes_viewer or []:
                vtk_w = getattr(node, "vtk_widget", None)
                if vtk_w is None:
                    continue
                try:
                    viewer_sn = str(
                        getattr(vtk_w.image_viewer, "metadata", {})
                        .get("series", {}).get("series_number", "")
                    )
                except Exception:
                    viewer_sn = ""
                if viewer_sn != sn:
                    continue

                _found_viewer = True
                current_count = vtk_w.get_count_of_slices()
                viewer_snapshot = build_series_completeness_snapshot(
                    sn,
                    expected_count=disk_count,
                    viewer_visible_count=current_count,
                )
                if viewer_snapshot.is_viewer_complete:
                    resolved.add((sn, expected_total))
                    break

                # Viewer behind â€” catch-up grow
                try:
                    loader = getattr(vtk_w, "_lazy_loader", None)
                    if loader is not None and hasattr(loader, "grow"):
                        new_count = loader.grow()
                        self._update_vtk_slice_range(vtk_w, node, new_count)
                        self._refresh_and_sync_metadata(sn, new_count)
                        self.logger.info(
                            "completion-sweep: grew series=%s from %d to %d (disk=%d)",
                            sn, current_count, new_count, disk_count,
                        )
                        grown_snapshot = build_series_completeness_snapshot(
                            sn,
                            expected_count=disk_count,
                            disk_count=disk_count,
                            viewer_visible_count=new_count,
                        )
                        if grown_snapshot.is_viewer_complete:
                            _finalize_progressive_series(
                                self,
                                sn,
                                final_count=new_count,
                                viewers=[(vtk_w, node)],
                                source='layer4_sweep',
                            )
                            resolved.add((sn, expected_total))
                except Exception as exc:
                    self.logger.debug(
                        "completion-sweep: grow failed series=%s: %s", sn, exc,
                    )
                break  # handle first matching viewer only

            if not _found_viewer:
                resolved.add((sn, expected_total))

        self._completion_sweep_series_set -= resolved

        # Stop timer when nothing left to verify
        if not self._completion_sweep_series_set:
            self._completion_sweep_timer.stop()
            self.logger.debug("completion-sweep: all series verified â€” timer stopped")

    def _activate_progressive_mode_on_viewers(self, series_number: str, total_expected: int):
        """After first progressive display, mark viewers for progressive growth.

        In Fast mode, also activates the ImageSliceBooster for آ±20 prefetch.
        """
        is_fast = self._is_fast_viewer_mode()
        for node in self.lst_nodes_viewer or []:
            vtk_w = getattr(node, "vtk_widget", None)
            if vtk_w is None:
                continue
            # Find viewers showing this series
            try:
                viewer_sn = str(
                    getattr(vtk_w.image_viewer, "metadata", {})
                    .get("series", {}).get("series_number", "")
                )
            except Exception:
                viewer_sn = ""
            if viewer_sn == str(series_number):
                try:
                    _raw_avail_getter = getattr(
                        vtk_w,
                        "_get_loaded_slice_count_for_progressive_sync",
                        None,
                    )
                    if callable(_raw_avail_getter):
                        avail = int(_raw_avail_getter() or 0)
                    else:
                        avail = int(vtk_w.get_count_of_slices() or 0)
                except Exception:
                    avail = 0
                vtk_w.enter_progressive_mode(total_expected, series_number)
                vtk_w.update_available_slice_count(avail)
                _set_progressive_lifecycle_state(
                    self,
                    str(series_number),
                    _PROGRESSIVE_STATE_PROGRESSIVE,
                    source="_activate_progressive_mode_on_viewers",
                    reason="entered_progressive_mode",
                )
                # Update slider to show full range
                slider = getattr(node, "slider", None)
                if slider is not None:
                    try:
                        slider.blockSignals(True)
                        slider.setMaximum(max(0, total_expected - 1))
                        slider.blockSignals(False)
                    except Exception:
                        pass

                # Fast mode: activate ImageSliceBooster for آ±20 prefetch
                if is_fast:
                    try:
                        loader = getattr(vtk_w, "_lazy_loader", None)
                        backend = getattr(loader, "backend", None) if loader is not None else None
                        if backend is not None:
                            paths = backend.get_file_paths()
                            if paths:
                                self._image_slice_booster.set_active(
                                    str(series_number), paths, center_slice=0,
                                )
                    except Exception as exc:
                        self.logger.debug("progressive: booster activation failed: %s", exc)

                self.logger.info(
                    "progressive: activated viewer series=%s avail=%d total=%d fast=%s",
                    series_number, avail, total_expected, is_fast,
                )

    def _apply_progressive_to_target_viewer(
        self, series_number: str, total: int, vtk_widget, node
    ):
        """Switch a specific viewer to a freshly loaded progressive series.

        Used when the user drag-dropped a series that wasn't on disk yet.
        The viewer was marked with ``_awaiting_series_number`` and a spinner
        was kept visible.  Now the first batch has been loaded â€” display it
        in that viewer, hide the spinner, and enter progressive mode.
        """
        try:
            # Clear the awaiting marker
            vtk_widget._awaiting_series_number = None

            # Look up loaded data from cache
            vtk_image_data, metadata, series_idx = self._get_series_by_number_fast(
                str(series_number)
            )
            if metadata is None or vtk_image_data is None:
                self.logger.warning(
                    "progressive-target: series=%s not in cache after load", series_number
                )
                self._hide_spinner_for_widget(vtk_widget)
                return

            slider = getattr(node, "slider", None) if node else None

            # Display the series on the target viewer
            self._display_loaded_series(
                series_number=str(series_number),
                series_idx=series_idx,
                vtk_image_data=vtk_image_data,
                metadata=metadata,
                flag_change_selected_widget=False,
                vtk_widget=vtk_widget,
                slider=slider,
                progressive_total=total,
            )

            # Enter progressive mode on this viewer
            avail = vtk_widget.get_count_of_slices()
            vtk_widget.enter_progressive_mode(total, str(series_number))
            vtk_widget.update_available_slice_count(avail)
            _set_progressive_lifecycle_state(
                self,
                str(series_number),
                _PROGRESSIVE_STATE_PROGRESSIVE,
                source="_apply_progressive_to_target_viewer",
                reason="awaiting_viewer_activated",
            )
            if slider is not None:
                try:
                    slider.blockSignals(True)
                    slider.setMaximum(max(0, total - 1))
                    slider.blockSignals(False)
                except Exception:
                    pass

            # Fast mode: activate ImageSliceBooster for آ±20 prefetch
            if self._is_fast_viewer_mode():
                try:
                    loader = getattr(vtk_widget, "_lazy_loader", None)
                    backend = getattr(loader, "backend", None) if loader else None
                    if backend is not None:
                        paths = backend.get_file_paths()
                        if paths:
                            self._image_slice_booster.set_active(
                                str(series_number), paths, center_slice=0,
                            )
                except Exception:
                    pass

            if not bool(getattr(self, '_first_series_displayed', False)):
                self._mark_first_series_displayed()

            self.logger.info(
                "progressive-target: displayed series=%s on awaiting viewer avail=%d total=%d",
                series_number, avail, total,
            )
        except Exception as exc:
            self.logger.warning("progressive-target: failed series=%s: %s", series_number, exc)
            self._hide_spinner_for_widget(vtk_widget)


