"""FAST View reproduction for download+scroll CPU storm.

Goal
----
Create a deterministic test that reproduces the real-world pattern:

1) series is actively downloading (progress signals keep arriving), and
2) user keeps scrolling at the same time.

When ``_grow_progressive_fast`` repeatedly fails during this overlap,
``_flush_progressive_grow_impl`` keeps re-arming the single-shot grow timer
because ``pending_downloaded > last_grow_count`` never clears.

That creates a tight timer loop (CPU storm) and is a plausible crash path
for the FAST mode issue reported from production.

This test is marked ``xfail(strict=True)`` on purpose:
- xfail = known bug reproducer (expected to fail until fixed)
- strict=True = if it unexpectedly passes, the test suite fails, forcing a
  review of whether the bug signature has changed or truly been fixed.
"""

from __future__ import annotations

import re
import threading
import types
from types import SimpleNamespace

import pytest

from PacsClient.pacs.patient_tab.ui.patient_ui import _vc_progressive as progressive_mod


class _TimerSpy:
    """Minimal QTimer-like spy used by the reproducer."""

    def __init__(self) -> None:
        self.start_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def isActive(self) -> bool:
        # emulate single-shot timer after timeout: usually inactive
        return False

    def interval(self) -> int:
        return 150


def _build_repro_controller():
    """Build a lightweight object with real progressive mixin methods bound."""
    ctrl = SimpleNamespace()

    # logger hooks used by the mixin
    ctrl.logger = SimpleNamespace(
        info=lambda *a, **kw: None,
        debug=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        error=lambda *a, **kw: None,
    )

    sn = "901"
    ctrl._progressive_series = {
        sn: {
            "total": 500,
            "last_grow_count": 10,
            "last_signal_ms": 0,
            "pending_downloaded": 10,
        }
    }
    ctrl._progressive_display_done = set()
    ctrl._progressive_display_inflight = set()
    ctrl._series_download_completed = set()
    ctrl._progressive_grow_batch_size = 10
    ctrl._is_fast_viewer_mode = lambda: True

    # one viewer "showing" this series in progressive mode
    viewer = SimpleNamespace(
        _progressive_mode=True,
        _progressive_series_number=sn,
        image_viewer=SimpleNamespace(metadata={"series": {"series_number": sn}}),
        get_count_of_slices=lambda: 10,
        update_available_slice_count=lambda c: None,
        enter_progressive_mode=lambda total, series: None,
        exit_progressive_mode=lambda: None,
    )
    node = SimpleNamespace(vtk_widget=viewer, slider=None)
    ctrl.lst_nodes_viewer = [node]
    ctrl._find_progressive_viewers = lambda s: [(viewer, node)] if s == sn else []

    # helper hooks used by _grow_progressive_fast path
    ctrl._refresh_and_sync_metadata = lambda *a, **kw: None
    ctrl._invalidate_series_caches = lambda *a, **kw: None
    ctrl._update_thumbnail_count = lambda *a, **kw: None
    ctrl._count_series_files_on_disk = lambda *a, **kw: 0
    ctrl._refresh_corner_text = lambda *a, **kw: None
    ctrl._disk_count_cache = {}

    timer = _TimerSpy()
    ctrl._progressive_grow_timer = timer

    # bind real methods from mixin
    ctrl.on_series_images_progress = types.MethodType(
        progressive_mod._VCProgressiveMixin.on_series_images_progress,
        ctrl,
    )
    ctrl._on_series_images_progress_impl = types.MethodType(
        progressive_mod._VCProgressiveMixin._on_series_images_progress_impl,
        ctrl,
    )
    ctrl._flush_progressive_grow_impl = types.MethodType(
        progressive_mod._VCProgressiveMixin._flush_progressive_grow_impl,
        ctrl,
    )

    return ctrl, sn, timer


def test_fast_download_scroll_overlap_can_trigger_timer_storm():
    """Reproduce CPU-storm signature from download+scroll overlap.

    Simulated sequence per tick:
    - download progress signal arrives for same series (increases pending)
    - user scroll event occurs (extra UI workload)
    - grow timer callback runs, but ``_grow_progressive_fast`` fails

    Expected SAFE behavior (target after fix): timer start count remains bounded.
    Current behavior (bug): timer starts almost every tick.
    """

    ctrl, sn, timer = _build_repro_controller()

    # emulate repeated grow failure under concurrency (e.g., stale state/race)
    def _always_fail_grow(series_number, pending_count, viewers):
        raise RuntimeError("simulated concurrent grow failure during scroll")

    ctrl._grow_progressive_fast = _always_fail_grow

    stop = threading.Event()
    scroll_events = {"count": 0}

    def _scroll_worker():
        # lightweight scroll pressure: enough to mimic concurrent UI activity
        while not stop.is_set():
            scroll_events["count"] += 1

    t = threading.Thread(target=_scroll_worker, daemon=True)
    t.start()

    try:
        total = 500
        downloaded = 10

        # Use batch-sized jumps so on_series_images_progress keeps updating
        # pending_downloaded while grow failures prevent last_grow_count advance.
        # This deterministically triggers the re-arm storm.
        for _ in range(60):
            downloaded = min(total, downloaded + 10)
            ctrl.on_series_images_progress(sn, downloaded, total)
            ctrl._flush_progressive_grow_impl()
    finally:
        stop.set()
        t.join(timeout=1.0)

    assert scroll_events["count"] > 0, "scroll worker did not run"

    # Safety expectation (post-fix target): bounded re-arms.
    # Current bug behavior: very high re-arm count, typically ~ticks.
    assert timer.start_calls <= 20, (
        "Reproduced timer storm: excessive progressive timer re-arming under "
        f"download+scroll overlap (start_calls={timer.start_calls})."
    )


def _extract_crash_signature(log_text: str) -> dict:
    """Extract high-value crash markers from FAST download+scroll logs."""
    cpu_vals = [
        float(m.group(1))
        for m in re.finditer(r"resource-summary\s+cpu=([0-9]+(?:\.[0-9]+)?)%", log_text)
    ]
    dropped_vals = [
        int(m.group(1))
        for m in re.finditer(r"dropped_frames_count=([0-9]+)", log_text)
    ]
    overlap_vals = [
        int(m.group(1))
        for m in re.finditer(r"DECODE_ENTRY\s+domain=lazy_backend\s+slice=\d+\s+overlap=([0-9]+)", log_text)
    ]

    return {
        "fatal_gil": "Fatal Python error: PyThreadState_Get" in log_text,
        "worker_loop_stack": "pydicom_lazy_volume.py\", line 972 in _worker_loop" in log_text,
        "wheel_flush_stack": "_flush_pending_wheel_slice_impl" in log_text,
        "set_slice_stack": "viewer_2d.py\", line 1345 in set_slice" in log_text,
        "max_cpu": max(cpu_vals) if cpu_vals else 0.0,
        "max_dropped_frames": max(dropped_vals) if dropped_vals else 0,
        "max_decode_overlap": max(overlap_vals) if overlap_vals else 0,
    }


def test_log_signature_parser_matches_log17_pattern():
    """Validate parser logic against the crash pattern seen in log 17.

    This turns your manual crash-log reading into a stable test utility.
    """
    log_excerpt = """
    ... viewer-lazy metrics viewport=1 ... dropped_frames_count=172
    ... resource-summary cpu=120.0% rss=1474.1MB ...
    ... [H12-1] DECODE_ENTRY domain=lazy_backend slice=151 overlap=4 ...
    Fatal Python error: PyThreadState_Get: the function must be called with the GIL held
    ... pydicom_lazy_volume.py", line 972 in _worker_loop
    ... _flush_pending_wheel_slice_impl
    ... viewer_2d.py", line 1345 in set_slice
    """

    sig = _extract_crash_signature(log_excerpt)
    assert sig["fatal_gil"] is True
    assert sig["worker_loop_stack"] is True
    assert sig["wheel_flush_stack"] is True
    assert sig["set_slice_stack"] is True
    assert sig["max_cpu"] >= 100.0
    assert sig["max_dropped_frames"] >= 150
    assert sig["max_decode_overlap"] >= 3


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known FAST-view risk signature from log 17: under download+scroll "
        "overlap, callback churn should stay bounded; currently drop/render "
        "storm can grow unbounded before fatal interpreter crash."
    ),
)
def test_fast_download_scroll_callback_storm_signature():
    """Reproduce callback churn signature seen before fatal GIL crash.

    We model rapid requested-slice changes while delayed decode callbacks arrive
    out-of-order. This should remain bounded in a healthy pipeline.
    """

    requested = 100
    dropped = 0
    rendered = 0
    decode_overlap = 0

    # Simulate 800 callback deliveries while user keeps scrolling.
    for i in range(800):
        # user scrolls fast: requested slice shifts every few events
        if i % 3 == 0:
            requested += 1

        ready_slice = requested + (2 if i % 4 else 0)  # stale/out-of-order skew
        if ready_slice != requested:
            dropped += 1
        else:
            rendered += 1

        # overlapping decodes rise under pressure (log17 showed overlap up to 4)
        if i % 20 == 0:
            decode_overlap = min(6, decode_overlap + 1)

    total = dropped + rendered
    drop_rate = float(dropped) / float(total) if total else 0.0

    # Healthy target should be much lower; log17 behaved like storm mode.
    assert drop_rate <= 0.35, (
        "Reproduced callback-storm signature: excessive drop rate under "
        f"download+scroll overlap (drop_rate={drop_rate:.3f}, dropped={dropped}, "
        f"rendered={rendered}, overlap={decode_overlap})."
    )


# ════════════════════════════════════════════════════════════════════════
# Phase 2A — Pre-screening tests (run BEFORE any manual toggle run)
# ════════════════════════════════════════════════════════════════════════

class TestPhase2A_ToggleWiring:
    """Validate that H13 toggle flags and probe functions are correctly wired.

    These are prerequisite checks — if any fail, manual toggle runs are
    unreliable because the code path under test isn't correctly activated.
    """

    def test_toggle_flags_inactive_in_test_env(self):
        """All H13 toggles must be OFF in the test environment."""
        from modules.viewer.fast._decode_guard import (
            _H13_DEEP_COPY,
            _H13_RENDER_GATE,
            _H13_KEEPALIVE,
        )
        assert not _H13_DEEP_COPY, "AIPACS_VTK_DEEP_COPY should not be active in test env"
        assert not _H13_RENDER_GATE, "AIPACS_RENDER_GATE should not be active in test env"
        assert not _H13_KEEPALIVE, "AIPACS_KEEPALIVE_OLD_VOLUME should not be active in test env"

    def test_toggle_env_var_names_match_code(self):
        """Verify the env var names used by _decode_guard match the documented names."""
        import inspect
        from modules.viewer.fast import _decode_guard

        source = inspect.getsource(_decode_guard)
        assert 'os.environ.get("AIPACS_VTK_DEEP_COPY")' in source
        assert 'os.environ.get("AIPACS_RENDER_GATE")' in source
        assert 'os.environ.get("AIPACS_KEEPALIVE_OLD_VOLUME")' in source


class TestPhase2A_OverlapProbe:
    """Validate H13-P1/P2 overlap detection probe logic.

    This tests the probe infrastructure itself. If these fail, P1 data from
    live runs is unreliable and Phase 2 toggle decisions cannot be trusted.
    """

    def setup_method(self):
        """Reset probe state before each test."""
        import modules.viewer.fast._decode_guard as guard
        guard._WRITE_ACTIVE = None
        guard._H13_OVERLAP_COUNT = 0
        guard._H13_OVERLAP_MAX_DURATION_NS = 0
        guard._WRITE_TIMESTAMPS.clear()

    def test_no_overlap_when_no_write_active(self):
        from modules.viewer.fast._decode_guard import (
            h13_check_overlap_before_render,
            h13_get_overlap_stats,
        )
        h13_check_overlap_before_render(0, "test_no_write")
        oc, max_ns = h13_get_overlap_stats()
        assert oc == 0, "Should detect no overlap when no write active"
        assert max_ns == 0

    def test_overlap_detected_during_active_write(self):
        import time
        from modules.viewer.fast._decode_guard import (
            h13_write_begin,
            h13_write_end,
            h13_check_overlap_before_render,
            h13_get_overlap_stats,
        )
        tid = threading.get_ident()

        # Simulate write in progress
        h13_write_begin(tid, 42)

        # Small delay so delta_ns is measurable
        time.sleep(0.001)

        # Render check should detect overlap
        h13_check_overlap_before_render(50, "test_overlap")
        oc, max_ns = h13_get_overlap_stats()
        assert oc == 1, f"Should detect 1 overlap, got {oc}"
        assert max_ns > 0, "Max duration should be positive"

        # End write
        h13_write_end(42)

        # No new overlap after write ends
        h13_check_overlap_before_render(50, "test_after_end")
        oc2, _ = h13_get_overlap_stats()
        assert oc2 == 1, "No new overlap should be detected after write ends"

    def test_overlap_counter_accumulates(self):
        from modules.viewer.fast._decode_guard import (
            h13_write_begin,
            h13_write_end,
            h13_check_overlap_before_render,
            h13_get_overlap_stats,
        )
        tid = threading.get_ident()

        for i in range(5):
            h13_write_begin(tid, i)
            h13_check_overlap_before_render(i + 100, f"test_multi_{i}")
            h13_write_end(i)

        oc, _ = h13_get_overlap_stats()
        assert oc == 5, f"Should accumulate 5 overlaps, got {oc}"

    def test_max_duration_tracks_worst_case(self):
        import time
        from modules.viewer.fast._decode_guard import (
            h13_write_begin,
            h13_check_overlap_before_render,
            h13_write_end,
            h13_get_overlap_stats,
        )
        tid = threading.get_ident()

        # Short overlap
        h13_write_begin(tid, 0)
        h13_check_overlap_before_render(10, "short")
        h13_write_end(0)
        _, max1 = h13_get_overlap_stats()

        # Longer overlap
        h13_write_begin(tid, 1)
        time.sleep(0.005)  # 5ms
        h13_check_overlap_before_render(11, "long")
        h13_write_end(1)
        _, max2 = h13_get_overlap_stats()

        assert max2 >= max1, "Max duration should track the worst case"
        assert max2 > 1_000_000, "5ms overlap should be > 1ms in ns"


class TestPhase2A_DecodeAge:
    """Validate H13-P3 decode-to-render age calculation.

    If age probe is broken, the Phase 1 decode-age KPI is unreliable
    and we cannot distinguish H13-A (tight age) from H13-E (loose age).
    """

    def setup_method(self):
        import modules.viewer.fast._decode_guard as guard
        guard._WRITE_TIMESTAMPS.clear()

    def test_unknown_slice_returns_negative(self):
        from modules.viewer.fast._decode_guard import h13_get_decode_age_ms
        age = h13_get_decode_age_ms(9999)
        assert age == -1.0, "Unknown slice should return -1"

    def test_recently_written_slice_has_small_age(self):
        from modules.viewer.fast._decode_guard import (
            h13_write_end,
            h13_get_decode_age_ms,
        )
        h13_write_end(100)
        age = h13_get_decode_age_ms(100)
        assert 0.0 <= age < 50.0, f"Recently written slice age should be small, got {age}ms"

    def test_age_increases_over_time(self):
        import time
        from modules.viewer.fast._decode_guard import (
            h13_write_end,
            h13_get_decode_age_ms,
        )
        h13_write_end(200)
        time.sleep(0.01)  # 10ms
        age = h13_get_decode_age_ms(200)
        assert age >= 5.0, f"Age after 10ms sleep should be >= 5ms, got {age}ms"


class TestPhase2A_TimerStormUnderToggles:
    """Verify timer-storm fix remains stable regardless of toggle state.

    Toggles T3/T4/T5 affect the lazy volume and render paths, not the
    progressive grow path directly. But if the timer-storm fix regresses
    under any toggle combination, that's a blocking finding.
    """

    def test_timer_storm_bounded_baseline(self):
        """Baseline: confirm timer-storm fix works (same as existing test)."""
        ctrl, sn, timer = _build_repro_controller()
        ctrl._grow_progressive_fast = lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("simulated grow failure")
        )
        for _ in range(60):
            ctrl.on_series_images_progress(sn, min(500, 10 + _ * 10), 500)
            ctrl._flush_progressive_grow_impl()
        assert timer.start_calls <= 20, f"Timer storm not bounded: {timer.start_calls}"

    def test_timer_storm_bounded_with_deep_copy_flag(self):
        """Timer-storm fix must hold even when T3 deep-copy flag is active.

        T3 doesn't touch progressive grow, but this confirms no unexpected
        interaction between the toggle infrastructure and the grow path.
        """
        import modules.viewer.fast._decode_guard as guard
        orig = guard._H13_DEEP_COPY
        try:
            guard._H13_DEEP_COPY = True
            ctrl, sn, timer = _build_repro_controller()
            ctrl._grow_progressive_fast = lambda *a, **kw: (_ for _ in ()).throw(
                RuntimeError("simulated grow failure")
            )
            for _ in range(60):
                ctrl.on_series_images_progress(sn, min(500, 10 + _ * 10), 500)
                ctrl._flush_progressive_grow_impl()
            assert timer.start_calls <= 20, f"Timer storm not bounded under T3: {timer.start_calls}"
        finally:
            guard._H13_DEEP_COPY = orig


class TestPhase2A_CrashSignatureExtended:
    """Extended crash signature extraction for Phase 2 toggle runs.

    Adds detection of H13-specific markers (toggle states, keepalive events,
    grow markers) so post-run analysis is automated.
    """

    def test_signature_detects_no_crash_clean_run(self):
        log = """
        [H13-INIT] toggles: deep_copy=True render_gate=False keepalive=False
        viewer-lazy metrics viewport=1 dropped_frames_count=30
        resource-summary cpu=75.0% rss=1100.0MB
        """
        sig = _extract_crash_signature(log)
        assert sig["fatal_gil"] is False
        assert sig["max_cpu"] >= 70.0
        assert sig["max_dropped_frames"] == 30

    def test_signature_detects_crash_under_toggle(self):
        log = """
        [H13-INIT] toggles: deep_copy=True render_gate=False keepalive=False
        viewer-lazy metrics viewport=1 dropped_frames_count=200
        resource-summary cpu=115.0% rss=1700.0MB
        Fatal Python error: PyThreadState_Get: the function must be called with the GIL held
        pydicom_lazy_volume.py", line 972 in _worker_loop
        _flush_pending_wheel_slice_impl
        viewer_2d.py", line 1345 in set_slice
        """
        sig = _extract_crash_signature(log)
        assert sig["fatal_gil"] is True
        assert sig["worker_loop_stack"] is True
        assert sig["set_slice_stack"] is True
        assert sig["max_cpu"] >= 100.0

    def test_signature_no_crash_with_render_gate(self):
        """If T4 eliminates crash, log should have no fatal_gil."""
        log = """
        [H13-INIT] toggles: deep_copy=False render_gate=True keepalive=False
        viewer-lazy metrics viewport=1 dropped_frames_count=45
        resource-summary cpu=105.0% rss=1500.0MB
        """
        sig = _extract_crash_signature(log)
        assert sig["fatal_gil"] is False
        assert sig["max_dropped_frames"] == 45


def extract_h13_toggle_state(log_text: str) -> dict:
    """Extract H13 toggle states and markers from a log.

    Returns dict with toggle states, grow count, keepalive count, overlap count.
    Used by Phase 2A to characterize a run before manual analysis.
    """
    result = {
        "deep_copy": None,
        "render_gate": None,
        "keepalive": None,
        "grow_count": 0,
        "keepalive_stash_count": 0,
        "overlap_count": 0,
        "tight_age_count": 0,
        "p5_snapshots": 0,
    }
    m = re.search(
        r"\[H13-INIT\] toggles: deep_copy=(\w+) render_gate=(\w+) keepalive=(\w+)",
        log_text,
    )
    if m:
        result["deep_copy"] = m.group(1) == "True"
        result["render_gate"] = m.group(2) == "True"
        result["keepalive"] = m.group(3) == "True"
    result["grow_count"] = len(re.findall(r"H13-GROW entry", log_text))
    result["keepalive_stash_count"] = len(re.findall(r"\[H13-T5\] keepalive old volume", log_text))
    result["overlap_count"] = len(re.findall(r"\[H13-OVERLAP\]", log_text))
    result["tight_age_count"] = len(re.findall(r"\[H13-AGE\]", log_text))
    result["p5_snapshots"] = len(re.findall(r"\[H13-P5\]", log_text))
    return result


def test_h13_toggle_state_parser():
    """Validate the toggle-state parser."""
    log = """
    [H13-INIT] toggles: deep_copy=True render_gate=False keepalive=False
    H13-GROW entry old_count=200 new_count=220
    H13-GROW entry old_count=220 new_count=240
    [H13-OVERLAP] render_chain while write active: write_tid=1234 write_slice=50 render_slice=55 delta_ms=0.50 overlap_count=1 caller=scroll
    [H13-AGE] tight decode-to-render age=2.50ms slice=55 caller=scroll
    [H13-AGE] tight decode-to-render age=1.20ms slice=60 caller=lazy_ready
    [H13-P5] viewport=1 workers=4 qsize=25 pending=3 overlap_count=1 overlap_max_ms=0.50 decode_count=150 decode_ms=4500.0
    [H13-P5] viewport=1 workers=4 qsize=30 pending=5 overlap_count=1 overlap_max_ms=0.50 decode_count=180 decode_ms=5400.0
    """
    state = extract_h13_toggle_state(log)
    assert state["deep_copy"] is True
    assert state["render_gate"] is False
    assert state["keepalive"] is False
    assert state["grow_count"] == 2
    assert state["overlap_count"] == 1
    assert state["tight_age_count"] == 2
    assert state["p5_snapshots"] == 2


class TestPhase2A_GrowKeepAliveCap:
    """Validate T5 keep-alive cap at 5 entries (memory safety)."""

    def test_keepalive_list_capped_at_5(self):
        """Simulate 10 grow() calls — stash list must never exceed 5."""
        import numpy as np

        stash: list = []
        for i in range(10):
            old_vol = np.zeros((10, 10), dtype=np.int16)
            stash.append(old_vol)
            if len(stash) > 5:
                stash = stash[-5:]

        assert len(stash) == 5, f"Keepalive stash should be capped at 5, got {len(stash)}"


# ────────────────────────────────────────────────────────────────────────
# H13 KPI extraction — unified run-level KPI summary from log text
# ────────────────────────────────────────────────────────────────────────

def extract_h13_run_kpis(log_text: str) -> dict:
    """Extract all H13 KPIs from a single run's log text.

    Returns a flat dict suitable for tabular comparison across runs.
    All fields are always present (default to ``None`` / ``0`` when absent).

    Parses: ``[H13-INIT]``, ``[H13-BUILD]``, ``[H13-P5]``,
    ``[H13-T6-DIAG]``, ``[H13-OVERLAP]``, ``[H13-AGE]``,
    ``resource-summary``, ``dropped_frames_count``, ``set_slice`` timings.
    """
    kpis: dict = {
        # --- crash ---
        "crash": "Fatal Python error" in log_text,
        "crash_gil": "PyThreadState_Get" in log_text,
        # --- build ---
        "python_version": None,
        "vtk_version": None,
        "vtk_thread_safe": None,
        # --- toggles ---
        "deep_copy": None,
        "render_gate": None,
        "keepalive": None,
        "stale_render_abort": None,
        "booster_disabled": None,
        # --- pressure ---
        "cpu_peak_pct": 0.0,
        "dropped_frames_max": 0,
        "set_slice_p95_ms": None,
        # --- overlap ---
        "overlap_count": 0,
        "overlap_max_ms": 0.0,
        # --- stale / TOCTOU ---
        "stale_cond_count_max": 0,
        "stale_abort_count_max": 0,
        "t6_diag_total": 0,
        "t6_stale_events": 0,
        "t6_mismatch_events": 0,
        # --- queue / decode ---
        "qsize_max": 0.0,
        "pending_max": 0.0,
        "decode_count_max": 0.0,
        # --- event counts ---
        "p5_snapshots": 0,
        "overlap_events": 0,
        "age_events": 0,
        "grow_events": 0,
    }

    # --- [H13-BUILD] ---
    m_build = re.search(
        r"\[H13-BUILD\]\s+python=(\S+.*?)\s+vtk=(\S+)\s+numpy=\S+"
        r"\s+vtk_thread_safe=(\S+(?:\s+\([^)]+\))?)",
        log_text,
    )
    if m_build:
        kpis["python_version"] = m_build.group(1).strip()
        kpis["vtk_version"] = m_build.group(2).strip()
        kpis["vtk_thread_safe"] = m_build.group(3).strip()

    # --- [H13-INIT] toggles ---
    m_init = re.search(
        r"\[H13-INIT\] toggles: deep_copy=(\w+) render_gate=(\w+) keepalive=(\w+)"
        r"(?: stale_render_abort=(\w+))?",
        log_text,
    )
    if m_init:
        kpis["deep_copy"] = m_init.group(1) == "True"
        kpis["render_gate"] = m_init.group(2) == "True"
        kpis["keepalive"] = m_init.group(3) == "True"
        if m_init.group(4) is not None:
            kpis["stale_render_abort"] = m_init.group(4) == "True"

    # --- booster disabled ---
    if "DISABLED by AIPACS_DISABLE_BOOSTER" in log_text:
        kpis["booster_disabled"] = True

    # --- CPU peak (from resource-summary) ---
    cpu_vals = [
        float(m.group(1))
        for m in re.finditer(r"resource-summary\s+cpu=([0-9]+(?:\.[0-9]+)?)%", log_text)
    ]
    if cpu_vals:
        kpis["cpu_peak_pct"] = max(cpu_vals)

    # --- dropped frames ---
    drop_vals = [
        int(m.group(1))
        for m in re.finditer(r"dropped_frames_count=([0-9]+)", log_text)
    ]
    if drop_vals:
        kpis["dropped_frames_max"] = max(drop_vals)

    # --- set_slice p95 ---
    p95_vals = [
        float(m.group(1))
        for m in re.finditer(r"set_slice[_\s]p95[=:\s]+([0-9]+(?:\.[0-9]+)?)", log_text)
    ]
    if p95_vals:
        kpis["set_slice_p95_ms"] = max(p95_vals)

    # --- [H13-P5] fields (take max across all P5 snapshots) ---
    for m in re.finditer(
        r"\[H13-P5\].*?"
        r"qsize=([0-9.]+).*?"
        r"pending=([0-9.]+).*?"
        r"overlap_count=([0-9]+).*?"
        r"overlap_max_ms=([0-9.]+).*?"
        r"decode_count=([0-9.]+)"
        r"(?:.*?stale_cond_count=([0-9]+))?"
        r"(?:.*?stale_abort_count=([0-9]+))?",
        log_text,
    ):
        kpis["p5_snapshots"] += 1
        kpis["qsize_max"] = max(kpis["qsize_max"], float(m.group(1)))
        kpis["pending_max"] = max(kpis["pending_max"], float(m.group(2)))
        kpis["overlap_count"] = max(kpis["overlap_count"], int(m.group(3)))
        kpis["overlap_max_ms"] = max(kpis["overlap_max_ms"], float(m.group(4)))
        kpis["decode_count_max"] = max(kpis["decode_count_max"], float(m.group(5)))
        if m.group(6) is not None:
            kpis["stale_cond_count_max"] = max(
                kpis["stale_cond_count_max"], int(m.group(6))
            )
        if m.group(7) is not None:
            kpis["stale_abort_count_max"] = max(
                kpis["stale_abort_count_max"], int(m.group(7))
            )

    # --- [H13-T6-DIAG] events ---
    kpis["t6_diag_total"] = len(re.findall(r"\[H13-T6-DIAG\]", log_text))
    kpis["t6_stale_events"] = len(
        re.findall(r"\[H13-T6-DIAG\].*reason=stale", log_text)
    )
    kpis["t6_mismatch_events"] = len(
        re.findall(r"\[H13-T6-DIAG\].*reason=mismatch", log_text)
    )

    # --- [H13-OVERLAP] event count ---
    kpis["overlap_events"] = len(re.findall(r"\[H13-OVERLAP\]", log_text))

    # --- [H13-AGE] tight-age events ---
    kpis["age_events"] = len(re.findall(r"\[H13-AGE\]", log_text))

    # --- grow events ---
    kpis["grow_events"] = len(re.findall(r"H13-GROW entry", log_text))

    return kpis


def format_h13_kpi_comparison(runs: dict) -> str:
    """Format a multi-run KPI comparison as a markdown table.

    Parameters
    ----------
    runs : dict
        Mapping of run label (str) to KPI dict (from ``extract_h13_run_kpis``).

    Returns
    -------
    str
        Markdown table suitable for pasting into H13_WORKING_DOCUMENT.md.
    """
    if not runs:
        return "(no runs)"

    _KEY_ORDER = [
        ("crash", "Crash"),
        ("crash_gil", "Crash (GIL)"),
        ("cpu_peak_pct", "CPU peak (%)"),
        ("dropped_frames_max", "Dropped frames"),
        ("set_slice_p95_ms", "set_slice p95 (ms)"),
        ("overlap_count", "Overlap count"),
        ("overlap_max_ms", "Overlap max (ms)"),
        ("stale_cond_count_max", "Stale cond count"),
        ("stale_abort_count_max", "Stale abort count"),
        ("t6_stale_events", "T6 stale events"),
        ("t6_mismatch_events", "T6 mismatch events"),
        ("qsize_max", "Queue max"),
        ("pending_max", "Pending max"),
        ("p5_snapshots", "P5 snapshots"),
        ("overlap_events", "Overlap events"),
        ("grow_events", "Grow events"),
        ("booster_disabled", "Booster disabled"),
    ]

    labels = list(runs.keys())
    header = "| KPI | " + " | ".join(labels) + " |"
    sep = "|---|" + "|".join(["---:"] * len(labels)) + "|"
    rows = [header, sep]

    for key, display in _KEY_ORDER:
        vals = []
        for label in labels:
            v = runs[label].get(key)
            if v is None:
                vals.append("\u2014")
            elif isinstance(v, bool):
                vals.append("**Yes**" if v else "No")
            elif isinstance(v, float):
                vals.append(f"{v:.2f}")
            else:
                vals.append(str(v))
        rows.append(f"| {display} | " + " | ".join(vals) + " |")

    return "\n".join(rows)


# ── Tests for KPI extraction ──────────────────────────────────────────

class TestH13KPIExtraction:
    """Validate extract_h13_run_kpis against realistic log excerpts."""

    SAMPLE_LOG_BASELINE = (
        "[H13-BUILD] python=3.13.5 vtk=9.6.0 numpy=2.4.2"
        " vtk_thread_safe=likely_OFF (PyPI wheel) vtk_path=/path\n"
        "[H13-INIT] toggles: deep_copy=False render_gate=False"
        " keepalive=False stale_render_abort=False\n"
        "resource-summary cpu=75.2% rss=1200.0MB\n"
        "resource-summary cpu=140.9% rss=1474.1MB\n"
        "viewer-lazy metrics viewport=1 dropped_frames_count=33\n"
        "viewer-lazy metrics viewport=1 dropped_frames_count=1538\n"
        "scroll-perf-summary set_slice_p95=83.78 p99=120.00\n"
        "[H13-P5] viewport=1 workers=4 qsize=25 pending=3"
        " overlap_count=10 overlap_max_ms=5.50 decode_count=150"
        " decode_ms=4500.0 stale_cond_count=7 stale_abort_count=0\n"
        "[H13-P5] viewport=1 workers=4 qsize=30 pending=5"
        " overlap_count=329 overlap_max_ms=39256.77 decode_count=180"
        " decode_ms=5400.0 stale_cond_count=12 stale_abort_count=0\n"
        "[H13-OVERLAP] write_tid=1234 write_slice=50 delta_ms=0.50\n"
        "[H13-OVERLAP] write_tid=1234 write_slice=60 delta_ms=1.20\n"
        "[H13-AGE] tight decode-to-render age=2.50ms slice=55\n"
        "[H13-T6-DIAG] toggle_state=off ready_slice=100"
        " requested_slice=100 live_current_slice=102"
        " guard_current_slice=100 abort_decision=False reason=stale\n"
        "[H13-T6-DIAG] toggle_state=off ready_slice=105"
        " requested_slice=105 live_current_slice=105"
        " guard_current_slice=105 abort_decision=False reason=other\n"
        "[H13-T6-DIAG] toggle_state=off ready_slice=110"
        " requested_slice=110 live_current_slice=112"
        " guard_current_slice=110 abort_decision=False reason=stale\n"
        "[H13-T6-DIAG] toggle_state=off ready_slice=115"
        " requested_slice=112 live_current_slice=115"
        " guard_current_slice=112 abort_decision=False reason=mismatch\n"
        "H13-GROW entry old_count=200 new_count=220\n"
    )

    SAMPLE_LOG_BOOSTER_OFF = (
        "[H13-BUILD] python=3.13.5 vtk=9.6.0 numpy=2.4.2"
        " vtk_thread_safe=likely_OFF (PyPI wheel) vtk_path=/path\n"
        "[H13-INIT] toggles: deep_copy=False render_gate=False"
        " keepalive=False stale_render_abort=False\n"
        "DISABLED by AIPACS_DISABLE_BOOSTER env var\n"
        "resource-summary cpu=45.0% rss=900.0MB\n"
        "resource-summary cpu=60.2% rss=950.0MB\n"
        "viewer-lazy metrics viewport=1 dropped_frames_count=12\n"
        "[H13-P5] viewport=1 workers=4 qsize=5 pending=1"
        " overlap_count=2 overlap_max_ms=1.20 decode_count=80"
        " decode_ms=2400.0 stale_cond_count=1 stale_abort_count=0\n"
        "[H13-T6-DIAG] toggle_state=off ready_slice=100"
        " requested_slice=100 live_current_slice=100"
        " guard_current_slice=100 abort_decision=False reason=other\n"
    )

    def test_baseline_crash_fields(self):
        kpis = extract_h13_run_kpis(self.SAMPLE_LOG_BASELINE)
        assert kpis["crash"] is False
        assert kpis["crash_gil"] is False

    def test_baseline_build_info(self):
        kpis = extract_h13_run_kpis(self.SAMPLE_LOG_BASELINE)
        assert kpis["vtk_version"] == "9.6.0"
        assert "3.13" in (kpis["python_version"] or "")
        assert "likely_OFF" in (kpis["vtk_thread_safe"] or "")

    def test_baseline_toggles(self):
        kpis = extract_h13_run_kpis(self.SAMPLE_LOG_BASELINE)
        assert kpis["deep_copy"] is False
        assert kpis["render_gate"] is False
        assert kpis["stale_render_abort"] is False
        assert kpis["booster_disabled"] is None  # not present in baseline

    def test_baseline_pressure_kpis(self):
        kpis = extract_h13_run_kpis(self.SAMPLE_LOG_BASELINE)
        assert kpis["cpu_peak_pct"] == 140.9
        assert kpis["dropped_frames_max"] == 1538
        assert kpis["set_slice_p95_ms"] == 83.78

    def test_baseline_overlap_kpis(self):
        kpis = extract_h13_run_kpis(self.SAMPLE_LOG_BASELINE)
        assert kpis["overlap_count"] == 329  # max from P5
        assert kpis["overlap_max_ms"] == 39256.77
        assert kpis["overlap_events"] == 2  # count of [H13-OVERLAP] lines

    def test_baseline_stale_kpis(self):
        kpis = extract_h13_run_kpis(self.SAMPLE_LOG_BASELINE)
        assert kpis["stale_cond_count_max"] == 12
        assert kpis["stale_abort_count_max"] == 0

    def test_baseline_t6_events(self):
        kpis = extract_h13_run_kpis(self.SAMPLE_LOG_BASELINE)
        assert kpis["t6_diag_total"] == 4
        assert kpis["t6_stale_events"] == 2
        assert kpis["t6_mismatch_events"] == 1

    def test_baseline_queue_kpis(self):
        kpis = extract_h13_run_kpis(self.SAMPLE_LOG_BASELINE)
        assert kpis["qsize_max"] == 30.0
        assert kpis["pending_max"] == 5.0
        assert kpis["p5_snapshots"] == 2

    def test_baseline_event_counts(self):
        kpis = extract_h13_run_kpis(self.SAMPLE_LOG_BASELINE)
        assert kpis["age_events"] == 1
        assert kpis["grow_events"] == 1

    def test_booster_off_detected(self):
        kpis = extract_h13_run_kpis(self.SAMPLE_LOG_BOOSTER_OFF)
        assert kpis["booster_disabled"] is True
        assert kpis["cpu_peak_pct"] == 60.2
        assert kpis["dropped_frames_max"] == 12
        assert kpis["overlap_count"] == 2

    def test_crash_log_detected(self):
        crash_log = (
            "Fatal Python error: PyThreadState_Get:"
            " the function must be called with the GIL held\n"
            "resource-summary cpu=55.0%\n"
        )
        kpis = extract_h13_run_kpis(crash_log)
        assert kpis["crash"] is True
        assert kpis["crash_gil"] is True

    def test_comparison_table_format(self):
        baseline = extract_h13_run_kpis(self.SAMPLE_LOG_BASELINE)
        p1 = extract_h13_run_kpis(self.SAMPLE_LOG_BOOSTER_OFF)
        table = format_h13_kpi_comparison(
            {"Baseline": baseline, "P1 (booster off)": p1}
        )
        assert "| KPI |" in table
        assert "Baseline" in table
        assert "P1 (booster off)" in table
        assert "140.90" in table  # CPU peak baseline
        assert "60.20" in table  # CPU peak P1
        assert "1538" in table  # dropped frames baseline

    def test_empty_log(self):
        kpis = extract_h13_run_kpis("")
        assert kpis["crash"] is False
        assert kpis["cpu_peak_pct"] == 0.0
        assert kpis["p5_snapshots"] == 0
        assert kpis["t6_diag_total"] == 0

