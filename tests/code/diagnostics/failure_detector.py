"""
tests/diagnostics/failure_detector.py
=======================================
20 Failure Signature detectors (FS-01 through FS-20) for the FAST viewer
diagnostic framework.

Each detector takes an event list + KPI dict and returns a FailureMatch or None.
All detectors are registered in FAILURE_SIGNATURES and can be called in batch
via ``detect_all()``.

Usage
-----
    from tests.diagnostics.failure_detector import detect_all
    from tests.diagnostics.kpi_collector import KpiCollector

    kpis = collector.collect()
    findings = detect_all(events, kpis, state_machines=sm.machines())
    for f in findings:
        print(f.code, f.title, f.evidence)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from tests.diagnostics.event_log import (
    EventEntry,
    ET_PROGRESSIVE_START,
    ET_PROGRESSIVE_GROW,
    ET_PROGRESSIVE_STALE,
    ET_PROGRESSIVE_STALE_EXHAUSTED,
    ET_PROGRESSIVE_COMPLETE,
    ET_PROGRESSIVE_MODE_ENTERED,
    ET_PROGRESSIVE_MODE_EXITED,
    ET_METADATA_REFRESH_DONE,
    ET_GROW_CALLED,
    ET_GROW_RETURNED,
    ET_DECODE_SLICE_READY,
    ET_DECODE_FAILED,
    ET_LOADER_RELEASED,
    ET_BACKEND_BIND,
    ET_SERIES_SWITCH_BEGIN,
    ET_SERIES_SWITCH_DONE,
    ET_SERIES_PROGRESS,
    ET_INFLIGHT_SET,
    ET_INFLIGHT_CLEARED,
    ET_DONE_GUARD_SET,
    ET_WIDGET_DESTROYED,
    ET_MEMORY_SNAPSHOT,
    ET_EXCEPTION_SWALLOWED,
    ET_COMPLETION_VERIFY_DONE,
)
from tests.diagnostics.kpi_collector import (
    T05_METADATA_REFRESH_MAX_MS,
    C06_DECODE_FAILED_SIGNALS,
    C16_EXCEPTIONS_SWALLOWED,
    C01_PROGRESSIVE_START_CALLS,
    C11_PROGRESS_SIGNALS_RECEIVED,
    S04_STALE_MAX_RETRY_REACHED,
    S05_INFLIGHT_STILL_SET_AT_END,
    S07_PROGRESSIVE_STILL_ACTIVE_AT_END,
    T01_FIRST_PROGRESS_TO_FIRST_GROW_MS,
    M02_RSS_MB_AT_PEAK,
    M03_RSS_MB_AT_END,
    C02_GROW_CALLS,
    C03_GROW_STALE_RETURNS,
)


# ─── FailureMatch dataclass ───────────────────────────────────────────────────

@dataclass
class FailureMatch:
    code: str           # FS-01 … FS-20
    title: str
    severity: str       # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    evidence: Dict[str, Any] = field(default_factory=dict)
    hypothesis: str = ""  # Which hypothesis this supports (H1–H6)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "severity": self.severity,
            "hypothesis": self.hypothesis,
            "evidence": self.evidence,
        }


# ─── Helper: filter events ────────────────────────────────────────────────────

def _of_type(events: List[EventEntry], *types: str) -> List[EventEntry]:
    type_set = set(types)
    return [e for e in events if e.event_type in type_set]


def _field(e: EventEntry, key: str, default: Any = None) -> Any:
    return e.fields.get(key, default)


# ─── Individual detector functions ───────────────────────────────────────────
# Each returns Optional[FailureMatch].

def _fs01_inflight_stuck(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    **_,
) -> Optional[FailureMatch]:
    """FS-01: INFLIGHT_STUCK — inflight flag set but never cleared within 10s."""
    threshold_s = 10.0
    set_events = _of_type(events, ET_INFLIGHT_SET)
    cleared_events = _of_type(events, ET_INFLIGHT_CLEARED)
    cleared_keys = {_field(e, "key") for e in cleared_events}

    for e in set_events:
        key = _field(e, "key")
        if key not in cleared_keys:
            # Find how much time elapsed since set
            later = [ev for ev in events if ev.seq > e.seq]
            if later:
                elapsed = later[-1].ts - e.ts
                if elapsed > threshold_s:
                    return FailureMatch(
                        code="FS-01",
                        title="INFLIGHT_STUCK",
                        severity="CRITICAL",
                        hypothesis="H5",
                        evidence={
                            "key": key,
                            "elapsed_s": elapsed,
                            "set_seq": e.seq,
                            "threshold_s": threshold_s,
                        },
                    )
    return None


def _fs02_done_guard_never_reset(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    scenario_run_count: int = 1,
    **_,
) -> Optional[FailureMatch]:
    """FS-02: DONE_NEVER_RESET — same done-guard key present across re-opens."""
    done_events = _of_type(events, ET_DONE_GUARD_SET)
    seen: Dict[str, int] = {}
    for e in done_events:
        key = _field(e, "key", "?")
        seen[key] = seen.get(key, 0) + 1
    multi = {k: v for k, v in seen.items() if v > 1}
    if multi:
        return FailureMatch(
            code="FS-02",
            title="DONE_GUARD_KEY_SET_MULTIPLE_TIMES",
            severity="HIGH",
            hypothesis="H4",
            evidence={"duplicate_keys": multi},
        )
    if scenario_run_count > 1 and seen:
        # Done keys present: in a repeated-open scenario this is expected to collide
        return FailureMatch(
            code="FS-02",
            title="DONE_NEVER_RESET",
            severity="HIGH",
            hypothesis="H4",
            evidence={
                "done_keys": list(seen.keys()),
                "scenario_run_count": scenario_run_count,
                "note": "done-guard never reset between opens — second open will be blocked",
            },
        )
    return None


def _fs03_stale_exhausted(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    **_,
) -> Optional[FailureMatch]:
    """FS-03: STALE_EXHAUSTED — stale retry count reached max (5)."""
    exhausted = _of_type(events, ET_PROGRESSIVE_STALE_EXHAUSTED)
    if exhausted or kpis.get(S04_STALE_MAX_RETRY_REACHED):
        stale_count = len(_of_type(events, ET_PROGRESSIVE_STALE))
        return FailureMatch(
            code="FS-03",
            title="STALE_EXHAUSTED",
            severity="HIGH",
            hypothesis="H6",
            evidence={
                "exhaustion_events": len(exhausted),
                "total_stale_events": stale_count,
                "kpi_stale_max": kpis.get(S04_STALE_MAX_RETRY_REACHED),
            },
        )
    return None


def _fs04_metadata_stall(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    metadata_stall_threshold_ms: float = 200.0,
    **_,
) -> Optional[FailureMatch]:
    """FS-04: METADATA_STALL — _refresh_stored_metadata_instances took > threshold."""
    max_ms = kpis.get(T05_METADATA_REFRESH_MAX_MS, 0.0) or 0.0
    if max_ms > metadata_stall_threshold_ms:
        return FailureMatch(
            code="FS-04",
            title="METADATA_STALL",
            severity="CRITICAL",
            hypothesis="H1",
            evidence={
                "max_refresh_ms": max_ms,
                "threshold_ms": metadata_stall_threshold_ms,
            },
        )
    # Check individual events
    done_ev = _of_type(events, ET_METADATA_REFRESH_DONE)
    for e in done_ev:
        dur = _field(e, "duration_ms", 0)
        if dur and dur > metadata_stall_threshold_ms:
            return FailureMatch(
                code="FS-04",
                title="METADATA_STALL",
                severity="CRITICAL",
                hypothesis="H1",
                evidence={
                    "event_duration_ms": dur,
                    "threshold_ms": metadata_stall_threshold_ms,
                    "seq": e.seq,
                },
            )
    return None


def _fs05_grow_exception(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    **_,
) -> Optional[FailureMatch]:
    """FS-05: GROW_EXCEPTION — _grow_progressive_fast raised an exception."""
    exc_events = [
        e for e in _of_type(events, ET_EXCEPTION_SWALLOWED)
        if "grow" in str(_field(e, "location", "")).lower()
    ]
    if exc_events or (kpis.get(C16_EXCEPTIONS_SWALLOWED, 0) or 0) > 0:
        return FailureMatch(
            code="FS-05",
            title="GROW_EXCEPTION",
            severity="HIGH",
            hypothesis="H2",
            evidence={
                "grow_exception_events": len(exc_events),
                "total_exceptions_swallowed": kpis.get(C16_EXCEPTIONS_SWALLOWED, 0),
            },
        )
    return None


def _fs06_loader_released_early(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    **_,
) -> Optional[FailureMatch]:
    """FS-06: LOADER_RELEASED_EARLY — grow called after loader released."""
    released_seqs = {e.seq for e in _of_type(events, ET_LOADER_RELEASED)}
    grow_events = _of_type(events, ET_GROW_CALLED)
    late_grows = [
        e for e in grow_events
        if any(r < e.seq for r in released_seqs)
    ]
    if late_grows:
        return FailureMatch(
            code="FS-06",
            title="LOADER_RELEASED_EARLY",
            severity="CRITICAL",
            hypothesis="H2",
            evidence={
                "grow_after_release_count": len(late_grows),
                "first_late_grow_seq": late_grows[0].seq,
            },
        )
    return None


def _fs07_decode_failed_storm(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    window_s: float = 5.0,
    threshold: int = 10,
    **_,
) -> Optional[FailureMatch]:
    """FS-07: DECODE_FAILED_STORM — > threshold decode failures within window_s."""
    failed_evs = _of_type(events, ET_DECODE_FAILED)
    if len(failed_evs) < threshold:
        return None
    # Sliding-window check
    for i, e in enumerate(failed_evs):
        window_end = e.ts + window_s
        count = sum(1 for f in failed_evs[i:] if f.ts <= window_end)
        if count >= threshold:
            return FailureMatch(
                code="FS-07",
                title="DECODE_FAILED_STORM",
                severity="HIGH",
                hypothesis="H2",
                evidence={
                    "count_in_window": count,
                    "window_s": window_s,
                    "threshold": threshold,
                    "total_failures": len(failed_evs),
                },
            )
    return None


def _fs08_signal_queue_overflow(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    threshold: int = 50,
    **_,
) -> Optional[FailureMatch]:
    """FS-08: SIGNAL_QUEUE_OVERFLOW — many progress signals before any grow."""
    progress = _of_type(events, ET_SERIES_PROGRESS)
    grows = _of_type(events, ET_PROGRESSIVE_GROW, ET_GROW_RETURNED)
    if not grows:
        # No grows at all — check if many progress signals were received
        n = len(progress)
        if n >= threshold:
            return FailureMatch(
                code="FS-08",
                title="SIGNAL_QUEUE_OVERFLOW",
                severity="MEDIUM",
                hypothesis="H5",
                evidence={
                    "progress_signals": n,
                    "grow_calls": 0,
                    "threshold": threshold,
                },
            )
        return None
    first_grow_seq = grows[0].seq
    pre_grow = [e for e in progress if e.seq < first_grow_seq]
    if len(pre_grow) >= threshold:
        return FailureMatch(
            code="FS-08",
            title="SIGNAL_QUEUE_OVERFLOW",
            severity="MEDIUM",
            hypothesis="H5",
            evidence={
                "progress_before_first_grow": len(pre_grow),
                "threshold": threshold,
            },
        )
    return None


def _fs09_progressive_never_started(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    progress_threshold: int = 10,
    **_,
) -> Optional[FailureMatch]:
    """FS-09: PROGRESSIVE_NEVER_STARTED — 10+ progress signals, no progressive start."""
    n_progress = kpis.get(C11_PROGRESS_SIGNALS_RECEIVED, 0) or len(_of_type(events, ET_SERIES_PROGRESS))
    n_starts = kpis.get(C01_PROGRESSIVE_START_CALLS, 0) or len(_of_type(events, ET_PROGRESSIVE_START, ET_PROGRESSIVE_MODE_ENTERED))
    if n_progress >= progress_threshold and n_starts == 0:
        return FailureMatch(
            code="FS-09",
            title="PROGRESSIVE_NEVER_STARTED",
            severity="CRITICAL",
            hypothesis="H4",
            evidence={
                "progress_signals": n_progress,
                "progressive_starts": n_starts,
            },
        )
    return None


def _fs10_grow_count_regression(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    **_,
) -> Optional[FailureMatch]:
    """FS-10: GROW_COUNT_REGRESSION — grow returned fewer slices than previous grow."""
    grow_returns = _of_type(events, ET_GROW_RETURNED)
    counts = [_field(e, "count") for e in grow_returns if _field(e, "count") is not None]
    regressions = []
    for i in range(1, len(counts)):
        if counts[i] < counts[i - 1]:
            regressions.append({
                "prev": counts[i - 1],
                "current": counts[i],
                "seq": grow_returns[i].seq,
            })
    if regressions:
        return FailureMatch(
            code="FS-10",
            title="GROW_COUNT_REGRESSION",
            severity="HIGH",
            hypothesis="H1",
            evidence={"regressions": regressions},
        )
    return None


def _fs11_slice_ready_before_bind(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    **_,
) -> Optional[FailureMatch]:
    """FS-11: SLICE_READY_BEFORE_BIND — decode_slice_ready before backend bind."""
    binds = _of_type(events, ET_BACKEND_BIND)
    if not binds:
        first_bind_seq = 999999999
    else:
        first_bind_seq = binds[0].seq
    early_ready = [
        e for e in _of_type(events, ET_DECODE_SLICE_READY)
        if e.seq < first_bind_seq
    ]
    if early_ready:
        return FailureMatch(
            code="FS-11",
            title="SLICE_READY_BEFORE_BIND",
            severity="HIGH",
            hypothesis="H2",
            evidence={
                "early_ready_count": len(early_ready),
                "first_ready_seq": early_ready[0].seq,
                "first_bind_seq": first_bind_seq,
            },
        )
    return None


def _fs12_download_start_latency(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    threshold_ms: float = 2000.0,
    **_,
) -> Optional[FailureMatch]:
    """FS-12: DOWNLOAD_START_LATENCY — T-01 (first progress → first grow) > 2s."""
    latency = kpis.get(T01_FIRST_PROGRESS_TO_FIRST_GROW_MS, -1.0)
    if latency is None or latency < 0:
        return None
    if latency > threshold_ms:
        return FailureMatch(
            code="FS-12",
            title="DOWNLOAD_START_LATENCY",
            severity="MEDIUM",
            hypothesis="H5",
            evidence={
                "first_progress_to_first_grow_ms": latency,
                "threshold_ms": threshold_ms,
            },
        )
    return None


def _fs13_completion_layer2_missed(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    **_,
) -> Optional[FailureMatch]:
    """FS-13: COMPLETION_LAYER2_MISSED — download_complete but final grow < expected."""
    grow_returns = [
        _field(e, "count")
        for e in _of_type(events, ET_GROW_RETURNED)
        if _field(e, "count") is not None
    ]
    if not grow_returns:
        return None
    final_grow = max(grow_returns)
    # Check from state machine's expected total
    for sn, m in (machines or {}).items():
        # Look for a PROGRESSIVE_START event with total
        for ev in events:
            if ev.event_type in (ET_PROGRESSIVE_START, ET_PROGRESSIVE_MODE_ENTERED):
                expected = _field(ev, "total", 0)
                if expected and final_grow < expected:
                    return FailureMatch(
                        code="FS-13",
                        title="COMPLETION_LAYER2_MISSED",
                        severity="HIGH",
                        hypothesis="H6",
                        evidence={
                            "final_grow_count": final_grow,
                            "expected_total": expected,
                            "deficit": expected - final_grow,
                        },
                    )
    return None


def _fs14_loader_outlives_viewer(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    **_,
) -> Optional[FailureMatch]:
    """FS-14: LOADER_OUTLIVES_VIEWER — registry key still present after widget destroyed."""
    destroyed_evs = _of_type(events, ET_WIDGET_DESTROYED)
    released_evs = _of_type(events, ET_LOADER_RELEASED)
    if not destroyed_evs:
        return None
    last_destroyed_seq = max(e.seq for e in destroyed_evs)
    still_alive = [
        e for e in released_evs
        if e.seq > last_destroyed_seq
    ]
    if not still_alive:
        # Check registry directly at report time
        try:
            from modules.viewer.fast import lazy_volume_registry as reg
            remaining = len(reg._REGISTRY)
            if remaining > 0:
                return FailureMatch(
                    code="FS-14",
                    title="LOADER_OUTLIVES_VIEWER",
                    severity="CRITICAL",
                    hypothesis="H2",
                    evidence={
                        "registry_entries_at_end": remaining,
                    },
                )
        except Exception:
            pass
    return None


def _fs15_generation_mismatch(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    **_,
) -> Optional[FailureMatch]:
    """FS-15: GENERATION_MISMATCH — slice_ready arrived for a stale generation."""
    mismatches = [
        e for e in _of_type(events, ET_DECODE_SLICE_READY)
        if _field(e, "generation_mismatch", False)
    ]
    if mismatches:
        return FailureMatch(
            code="FS-15",
            title="GENERATION_MISMATCH",
            severity="HIGH",
            hypothesis="H3",
            evidence={
                "mismatch_count": len(mismatches),
                "first_seq": mismatches[0].seq,
            },
        )
    return None


def _fs16_inflight_task_orphan(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    **_,
) -> Optional[FailureMatch]:
    """FS-16: INFLIGHT_TASK_ORPHAN — series switch completed but inflight not cleared."""
    switch_ends = _of_type(events, ET_SERIES_SWITCH_DONE)
    inflight_set = _of_type(events, ET_INFLIGHT_SET)
    inflight_cleared = _of_type(events, ET_INFLIGHT_CLEARED)
    cleared_keys = {_field(e, "key") for e in inflight_cleared}

    for sw in switch_ends:
        # Find inflight keys set before this switch that were never cleared
        stuck = [
            e for e in inflight_set
            if e.seq < sw.seq and _field(e, "key") not in cleared_keys
        ]
        if stuck:
            return FailureMatch(
                code="FS-16",
                title="INFLIGHT_TASK_ORPHAN",
                severity="HIGH",
                hypothesis="H5",
                evidence={
                    "switch_seq": sw.seq,
                    "stuck_inflight_keys": [_field(e, "key") for e in stuck],
                },
            )
    return None


def _fs17_memory_pressure(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    rss_threshold_mb: float = 3000.0,
    **_,
) -> Optional[FailureMatch]:
    """FS-17: MEMORY_PRESSURE — RSS > 3GB during progressive grow."""
    peak_rss = kpis.get(M02_RSS_MB_AT_PEAK) or 0.0
    if peak_rss > rss_threshold_mb:
        return FailureMatch(
            code="FS-17",
            title="MEMORY_PRESSURE",
            severity="HIGH",
            hypothesis="H1",
            evidence={
                "peak_rss_mb": peak_rss,
                "threshold_mb": rss_threshold_mb,
                "delta_mb": kpis.get("M04_rss_delta_mb", 0.0),
            },
        )
    # Also check event log snapshots
    snapshots = _of_type(events, ET_MEMORY_SNAPSHOT)
    for e in snapshots:
        rss = _field(e, "rss_mb", 0)
        if rss and rss > rss_threshold_mb:
            return FailureMatch(
                code="FS-17",
                title="MEMORY_PRESSURE",
                severity="HIGH",
                hypothesis="H1",
                evidence={
                    "event_rss_mb": rss,
                    "threshold_mb": rss_threshold_mb,
                    "seq": e.seq,
                },
            )
    return None


def _fs18_done_guard_false_positive(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    **_,
) -> Optional[FailureMatch]:
    """FS-18: DONE_GUARD_FALSE_POSITIVE — series in done set, viewer showing 0 slices."""
    done_evs = _of_type(events, ET_DONE_GUARD_SET)
    grow_returns = _of_type(events, ET_GROW_RETURNED)
    if not done_evs:
        return None
    for de in done_evs:
        # Find the most recent grow before this done-guard
        prior_grows = [e for e in grow_returns if e.seq < de.seq]
        if not prior_grows:
            return FailureMatch(
                code="FS-18",
                title="DONE_GUARD_FALSE_POSITIVE",
                severity="CRITICAL",
                hypothesis="H4",
                evidence={
                    "done_guard_seq": de.seq,
                    "note": "done-guard set before any grow — viewer shows 0 slices",
                },
            )
    return None


def _fs19_progressive_mode_lost(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    **_,
) -> Optional[FailureMatch]:
    """FS-19: PROGRESSIVE_MODE_LOST — progressive exited before completion signal."""
    exits = _of_type(events, ET_PROGRESSIVE_MODE_EXITED)
    completes = _of_type(events, ET_PROGRESSIVE_COMPLETE)
    # Early exits: exit happened but no subsequent complete event
    for ex in exits:
        # Check if there was a complete within next N events
        subsequent = [
            e for e in completes if e.seq > ex.seq
        ]
        if not subsequent:
            # Was this a premature exit?  Check if there were more signal events after
            subsequent_progress = [
                e for e in _of_type(events, ET_SERIES_PROGRESS)
                if e.seq > ex.seq
            ]
            if subsequent_progress:
                return FailureMatch(
                    code="FS-19",
                    title="PROGRESSIVE_MODE_LOST",
                    severity="HIGH",
                    hypothesis="H6",
                    evidence={
                        "exit_seq": ex.seq,
                        "progress_after_exit": len(subsequent_progress),
                        "note": "progressive mode exited while download still in progress",
                    },
                )
    return None


def _fs20_timer_never_fires(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Dict,
    grow_interval_s: float = 5.0,
    **_,
) -> Optional[FailureMatch]:
    """FS-20: TIMER_NEVER_FIRES — progressive mode active > 5s but no grow call."""
    enter_evs = _of_type(events, ET_PROGRESSIVE_MODE_ENTERED)
    grow_evs = _of_type(events, ET_PROGRESSIVE_GROW, ET_GROW_CALLED)
    if not enter_evs:
        return None
    for en in enter_evs:
        first_grow_after = next(
            (g for g in grow_evs if g.seq > en.seq), None
        )
        if first_grow_after is None:
            # No grow at all — how far did we get in the log?
            later = [e for e in events if e.seq > en.seq]
            if later:
                elapsed = later[-1].ts - en.ts
                if elapsed > grow_interval_s:
                    return FailureMatch(
                        code="FS-20",
                        title="TIMER_NEVER_FIRES",
                        severity="CRITICAL",
                        hypothesis="H5",
                        evidence={
                            "elapsed_since_enter_s": elapsed,
                            "threshold_s": grow_interval_s,
                            "enter_seq": en.seq,
                        },
                    )
        else:
            elapsed = first_grow_after.ts - en.ts
            if elapsed > grow_interval_s:
                return FailureMatch(
                    code="FS-20",
                    title="TIMER_NEVER_FIRES",
                    severity="CRITICAL",
                    hypothesis="H5",
                    evidence={
                        "latency_to_first_grow_s": elapsed,
                        "threshold_s": grow_interval_s,
                        "enter_seq": en.seq,
                    },
                )
    return None


# ─── FAILURE_SIGNATURES registry ─────────────────────────────────────────────

FAILURE_SIGNATURES: List[Callable] = [
    _fs01_inflight_stuck,
    _fs02_done_guard_never_reset,
    _fs03_stale_exhausted,
    _fs04_metadata_stall,
    _fs05_grow_exception,
    _fs06_loader_released_early,
    _fs07_decode_failed_storm,
    _fs08_signal_queue_overflow,
    _fs09_progressive_never_started,
    _fs10_grow_count_regression,
    _fs11_slice_ready_before_bind,
    _fs12_download_start_latency,
    _fs13_completion_layer2_missed,
    _fs14_loader_outlives_viewer,
    _fs15_generation_mismatch,
    _fs16_inflight_task_orphan,
    _fs17_memory_pressure,
    _fs18_done_guard_false_positive,
    _fs19_progressive_mode_lost,
    _fs20_timer_never_fires,
]


# ─── Public API ──────────────────────────────────────────────────────────────

def detect_all(
    events: List[EventEntry],
    kpis: Dict[str, Any],
    machines: Optional[Dict] = None,
    **kwargs: Any,
) -> List[FailureMatch]:
    """Run all 20 failure signature detectors and return positive matches."""
    found: List[FailureMatch] = []
    for detector in FAILURE_SIGNATURES:
        try:
            result = detector(
                events=events,
                kpis=kpis,
                machines=machines or {},
                **kwargs,
            )
            if result is not None:
                found.append(result)
        except Exception:
            pass  # Never let a detector crash the framework
    return found


def severity_order(match: FailureMatch) -> int:
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    return order.get(match.severity, 99)
