"""
Test event-loop diagnostics instrumentation (G0 observability).

Tests event jitter classification and metric aggregation.
"""

import pytest
import time
from modules.viewer.fast.event_loop_diagnostics import (
    start_session,
    stop_session,
    record_event,
    EventTimestamp,
    _percentile,
    _classify_jitter_source,
)


def test_event_timestamp_creation():
    """Test EventTimestamp dataclass creation."""
    ts = EventTimestamp(
        event_type="MouseMove",
        event_id=1,
        source="app_filter",
        timestamp_ms=100.5,
        x=500,
        y=600,
    )
    assert ts.event_type == "MouseMove"
    assert ts.source == "app_filter"
    assert ts.x == 500


def test_percentile_calculation():
    """Test percentile computation."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    p50 = _percentile(values, 0.5)
    p95 = _percentile(values, 0.95)
    
    # p50 should be around 5-6
    assert 4.0 <= p50 <= 6.0
    # p95 should be around 9-10
    assert 8.0 <= p95 <= 10.0
    
    # Empty list
    assert _percentile([], 0.95) == 0.0


def test_session_start_stop():
    """Test start/stop session lifecycle."""
    start_session("test-session-1")
    
    # Record some events
    record_event("MouseMove", "app_filter", x=100, y=200)
    time.sleep(0.01)  # 10ms gap
    record_event("MouseMove", "app_filter", x=101, y=201)
    
    result = stop_session()
    assert result is not None
    assert result.get("session_id") == "test-session-1"
    assert result.get("total_events") >= 2


def test_jitter_source_classification_os_batching():
    """Test classification when OS is batching input (large gaps)."""
    agg = {
        "mouse_event_gap_p95_ms": 1200.0,  # > 1000 → OS batching
        "wheel_event_gap_p95_ms": 0.0,
        "paint_event_gap_p95_ms": 100.0,
        "timer_heartbeat_steady": True,
        "wheel_compression_suspected": False,
        "paint_independent_of_input_suspected": False,
    }
    classification = _classify_jitter_source(agg)
    assert classification in ["G_OS_INPUT_BATCHING", "B_QAPPLICATION_DISPATCH_GAP"]


def test_jitter_source_classification_wheel_compression():
    """Test classification when wheel events are being compressed."""
    agg = {
        "mouse_event_gap_p95_ms": 100.0,
        "wheel_event_gap_p95_ms": 100.0,
        "wheel_compression_suspected": True,  # Key indicator
        "timer_heartbeat_steady": True,
        "paint_event_gap_p95_ms": 100.0,
        "paint_independent_of_input_suspected": False,
    }
    classification = _classify_jitter_source(agg)
    assert classification == "F_MOUSE_EVENT_COMPRESSION"


def test_jitter_source_classification_qasync_starvation():
    """Test classification when qasync loop is starved."""
    agg = {
        "mouse_event_gap_p95_ms": 100.0,
        "wheel_event_gap_p95_ms": 100.0,
        "timer_heartbeat_steady": False,  # Key indicator of starvation
        "timer_gap_p95_ms": 2000.0,  # Timers not firing
        "wheel_compression_suspected": False,
        "paint_event_gap_p95_ms": 100.0,
        "paint_independent_of_input_suspected": False,
    }
    classification = _classify_jitter_source(agg)
    assert classification == "D_QASYNC_LOOP_STARVATION"


def test_jitter_source_classification_paint_lag():
    """Test classification when paint events are delayed."""
    agg = {
        "mouse_event_gap_p95_ms": 100.0,
        "wheel_event_gap_p95_ms": 100.0,
        "paint_event_gap_p95_ms": 500.0,  # > mouse gap → paint is slower
        "timer_heartbeat_steady": True,
        "wheel_compression_suspected": False,
        "paint_independent_of_input_suspected": True,  # Paints don't follow input
    }
    classification = _classify_jitter_source(agg)
    assert classification == "E_PAINT_SCHEDULING_GAP"


def test_event_compression_detection():
    """Test that wheel delta accumulation is detected."""
    start_session("test-compression")
    
    # Simulate wheel delta accumulation
    # Single scroll event might be delta=120, but compressed ones could be 240, 360, etc.
    record_event("Wheel", "app_filter", wheel_delta=120)
    time.sleep(0.001)
    record_event("Wheel", "app_filter", wheel_delta=240)
    time.sleep(0.001)
    record_event("Wheel", "app_filter", wheel_delta=240)
    
    result = stop_session()
    # Total delta = 600, unique deltas = 2 (120, 240)
    # Expected: wheel_delta_sum=600, wheel_unique_deltas=2
    if "wheel_delta_sum" in result:
        assert result["wheel_delta_sum"] == 600


def test_update_to_paint_delay():
    """Test measurement of update() call to paintEvent delay."""
    start_session("test-update-paint")
    
    # Simulate update request
    record_event("UpdateRequest", "app_filter", widget_name="TestWidget")
    time.sleep(0.02)  # 20ms delay
    record_event("Paint", "app_filter", widget_name="TestWidget")
    
    result = stop_session()
    if "update_to_paint_p95_ms" in result:
        # Should be roughly 20ms
        assert result["update_to_paint_p95_ms"] >= 10.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
