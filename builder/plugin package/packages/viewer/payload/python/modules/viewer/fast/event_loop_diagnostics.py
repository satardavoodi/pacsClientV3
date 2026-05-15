"""
Event loop and input delivery diagnostics.

Measures where event-delivery jitter originates in the Qt/qasync pipeline.
Collects timing for: QApplication entry → widget dispatch → handler → paint → presentation.

Classification targets:
  A) Qt input delivery gap (before QApplication receives from OS)
  B) QApplication → widget dispatch gap
  C) widget handler execution gap
  D) qasync loop starvation
  E) paint/update scheduling gap
  F) mouse event compression/coalescing
  G) native/OS-level input batching
  H) UNKNOWN_INPUT_JITTER
"""

import time
import threading
import os
from collections import defaultdict, deque
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

# Global diagnostics state
_lock = threading.Lock()
_session_enabled = False
_diagnostics_enabled_cache: Optional[bool] = None
_event_timeline: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))  # ~400 events per session
_current_session_start_ms: Optional[float] = None
_current_session_id: Optional[str] = None


def _is_diagnostics_enabled() -> bool:
    """Check if event-loop diagnostics are opt-in enabled."""
    global _diagnostics_enabled_cache
    if _diagnostics_enabled_cache is not None:
        return _diagnostics_enabled_cache
    enabled = str(os.getenv('AIPACS_EVENT_LOOP_DIAG', '')).strip() == '1'
    _diagnostics_enabled_cache = enabled
    return enabled


@dataclass
class EventTimestamp:
    """Single event timing entry."""
    event_type: str  # "MouseMove", "Wheel", "Paint", "Timer", "UpdateRequest"
    event_id: int  # Monotonic counter
    source: str  # "app_filter", "widget_filter", "handler", "paint", "update_call"
    timestamp_ms: float
    x: Optional[int] = None
    y: Optional[int] = None
    wheel_delta: Optional[int] = None
    widget_name: Optional[str] = None


def start_session(session_id: str) -> None:
    """Start collecting event diagnostics for a session (opt-in via AIPACS_EVENT_LOOP_DIAG=1)."""
    if not _is_diagnostics_enabled():
        return
    global _session_enabled, _current_session_start_ms, _current_session_id
    with _lock:
        _session_enabled = True
        _current_session_start_ms = time.perf_counter() * 1000.0
        _current_session_id = session_id
        _event_timeline.clear()
    logger.debug(f"[EVENT_DIAG] Session started: {session_id}")


def stop_session() -> Dict[str, Any]:
    """Stop collecting and return aggregated metrics (opt-in via AIPACS_EVENT_LOOP_DIAG=1)."""
    if not _is_diagnostics_enabled():
        return {}
    global _session_enabled, _current_session_start_ms, _current_session_id
    with _lock:
        _session_enabled = False
        session_id = _current_session_id
        events = {k: list(v) for k, v in _event_timeline.items()}
        _event_timeline.clear()
    
    if not events:
        return {}
    
    return _aggregate_events(events, session_id)


def record_event(event_type: str, source: str, x: Optional[int] = None,
                 y: Optional[int] = None, wheel_delta: Optional[int] = None,
                 widget_name: Optional[str] = None) -> None:
    """Record an event timestamp (thread-safe, opt-in via AIPACS_EVENT_LOOP_DIAG=1)."""
    if not _is_diagnostics_enabled() or not _session_enabled:
        return
    
    with _lock:
        if not _session_enabled:
            return
        
        key = f"{event_type}_{source}"
        now_ms = time.perf_counter() * 1000.0
        
        ts = EventTimestamp(
            event_type=event_type,
            event_id=len(_event_timeline.get(key, [])),
            source=source,
            timestamp_ms=now_ms,
            x=x, y=y,
            wheel_delta=wheel_delta,
            widget_name=widget_name
        )
        _event_timeline[key].append(ts)


def _aggregate_events(events: Dict[str, List[EventTimestamp]], session_id: Optional[str]) -> Dict[str, Any]:
    """Aggregate event timings into diagnostic KPIs."""
    
    agg = {
        "session_id": session_id,
        "total_events": sum(len(v) for v in events.values()),
    }
    
    # Extract timelines by event type
    mouse_moves = events.get("MouseMove_app_filter", []) or events.get("MouseMove_handler", [])
    wheels = events.get("Wheel_app_filter", []) or events.get("Wheel_handler", [])
    paints = events.get("Paint_paint", [])
    updates = events.get("UpdateRequest_update_call", [])
    timers = events.get("Timer_app_filter", [])
    
    # Compute inter-event gaps (in milliseconds)
    def compute_gaps(timeline: List[EventTimestamp]) -> Tuple[List[float], float, float]:
        """Returns (gaps, p95, max)."""
        if len(timeline) < 2:
            return [], 0.0, 0.0
        
        gaps = []
        for i in range(1, len(timeline)):
            gap = timeline[i].timestamp_ms - timeline[i-1].timestamp_ms
            gaps.append(gap)
        
        if not gaps:
            return gaps, 0.0, 0.0
        
        p95 = _percentile(gaps, 0.95)
        max_gap = max(gaps)
        return gaps, p95, max_gap
    
    # Mouse event analysis
    if mouse_moves:
        mouse_gaps, mouse_p95, mouse_max = compute_gaps(mouse_moves)
        agg["mouse_event_gap_p95_ms"] = mouse_p95
        agg["mouse_event_gap_max_ms"] = mouse_max
        agg["mouse_event_count"] = len(mouse_moves)
    
    # Wheel event analysis
    if wheels:
        wheel_gaps, wheel_p95, wheel_max = compute_gaps(wheels)
        agg["wheel_event_gap_p95_ms"] = wheel_p95
        agg["wheel_event_gap_max_ms"] = wheel_max
        agg["wheel_event_count"] = len(wheels)
        
        # Detect wheel delta accumulation (compression)
        total_delta = sum(e.wheel_delta or 0 for e in wheels)
        unique_deltas = len(set(e.wheel_delta for e in wheels if e.wheel_delta is not None))
        agg["wheel_delta_sum"] = total_delta
        agg["wheel_unique_deltas"] = unique_deltas
        agg["wheel_compression_suspected"] = (total_delta > unique_deltas * 10)  # heuristic
    
    # Paint event analysis
    if paints:
        paint_gaps, paint_p95, paint_max = compute_gaps(paints)
        agg["paint_event_gap_p95_ms"] = paint_p95
        agg["paint_event_gap_max_ms"] = paint_max
        agg["paint_event_count"] = len(paints)
    
    # Update-to-paint delay
    if updates and paints:
        u_times = [e.timestamp_ms for e in updates]
        p_times = [e.timestamp_ms for e in paints]
        
        # For each paint, find closest preceding update
        delays = []
        for p_time in p_times:
            preceding = [u for u in u_times if u <= p_time]
            if preceding:
                delay = p_time - max(preceding)
                delays.append(delay)
        
        if delays:
            agg["update_to_paint_p95_ms"] = _percentile(delays, 0.95)
            agg["update_to_paint_max_ms"] = max(delays)
    
    # Timer heartbeat analysis (detect if timers fire during gaps)
    if timers:
        timer_gaps, timer_p95, timer_max = compute_gaps(timers)
        agg["timer_gap_p95_ms"] = timer_p95
        agg["timer_gap_max_ms"] = timer_max
        agg["timer_count"] = len(timers)
        agg["timer_heartbeat_steady"] = (timer_p95 < 100.0)  # timers should fire frequently
    
    # Cross-event correlation: Do paints coincide with input events?
    if mouse_moves and paints:
        mouse_times = {e.timestamp_ms for e in mouse_moves}
        paints_within_50ms_of_input = sum(
            1 for p_time in [e.timestamp_ms for e in paints]
            if any(abs(p_time - m_time) < 50.0 for m_time in mouse_times)
        )
        agg["paint_within_50ms_of_input"] = paints_within_50ms_of_input
        agg["paint_independent_of_input_suspected"] = (
            paints_within_50ms_of_input < len(paints) * 0.5
        )
    
    # Classify the jitter source
    agg["jitter_source_classification"] = _classify_jitter_source(agg)
    
    return agg


def _percentile(values: List[float], p: float) -> float:
    """Compute percentile (0.0-1.0)."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * p)
    return sorted_vals[min(idx, len(sorted_vals) - 1)]


def _classify_jitter_source(agg: Dict[str, Any]) -> str:
    """Classify which component is causing event jitter."""
    
    # Gather evidence
    mouse_gap_p95 = agg.get("mouse_event_gap_p95_ms", 0.0)
    wheel_gap_p95 = agg.get("wheel_event_gap_p95_ms", 0.0)
    paint_gap_p95 = agg.get("paint_event_gap_p95_ms", 0.0)
    timer_heartbeat = agg.get("timer_heartbeat_steady", True)
    wheel_compression = agg.get("wheel_compression_suspected", False)
    paint_independent = agg.get("paint_independent_of_input_suspected", False)
    
    # Decision tree
    if wheel_compression:
        return "F_MOUSE_EVENT_COMPRESSION"  # Qt or OS is batching wheel events
    
    if not timer_heartbeat:
        return "D_QASYNC_LOOP_STARVATION"  # Timers aren't firing steadily
    
    if paint_gap_p95 > 100 and paint_gap_p95 > mouse_gap_p95:
        if paint_independent:
            return "E_PAINT_SCHEDULING_GAP"  # Paints don't follow input events
        else:
            return "C_WIDGET_HANDLER_GAP"  # Handler is slow or deferred
    
    if mouse_gap_p95 > 1000:
        return "G_OS_INPUT_BATCHING"  # OS is batching mouse events
    
    if mouse_gap_p95 > 500:
        return "B_QAPPLICATION_DISPATCH_GAP"  # QApplication dispatch is slow
    
    return "H_UNKNOWN_INPUT_JITTER"


# Optional: Hook into qasync to detect loop starvation
_qasync_loop_active = False
_qasync_burst_start_ms: Optional[float] = None
_qasync_burst_durations: List[float] = []

def record_qasync_burst_start() -> None:
    """Called when asyncio task burst starts."""
    global _qasync_burst_start_ms
    _qasync_burst_start_ms = time.perf_counter() * 1000.0

def record_qasync_burst_end() -> None:
    """Called when asyncio task burst ends."""
    global _qasync_burst_start_ms, _qasync_burst_durations
    if _qasync_burst_start_ms is not None:
        duration = (time.perf_counter() * 1000.0) - _qasync_burst_start_ms
        _qasync_burst_durations.append(duration)
        _qasync_burst_start_ms = None
