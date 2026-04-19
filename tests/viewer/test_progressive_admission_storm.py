"""tests/viewer/test_progressive_admission_storm.py
------------------------------------------------
Storm-focused regression tests for the progressive viewer admission gate.

Why this file exists
--------------------
The admission gate is meant to make FAST-view overlap *smoother* when the
Download Manager delivers a large burst of new slices (common on fast LAN / loopback
setups). But it also adds control-plane logic, so we need to prove two things:

1. It actually reduces per-tick viewer shock under a burst.
2. It does *not* introduce runaway background complexity.

These tests intentionally use deterministic proxy metrics rather than wall-clock
render timings, because CI machines vary wildly. The proxies are tied directly to
what the user feels and what the event loop pays for:

- peak visible jump: the biggest slice-window jump exposed in a single grow tick
- burst shock score: $\\sum (\\Delta visible)^2$ across a burst, which penalizes
  large one-shot admissions more than gradual ones
- tick count: how many grow passes are needed to drain a non-terminal burst
- timer restart count: a bounded proxy for background churn

Interpretation
--------------
A healthy admission gate should:
- reduce peak visible jump and shock score vs ungated behavior
- keep non-terminal drain complexity bounded by
    $\\lceil(pending-last\\_grow)/admit\\_batch\\rceil$
- keep terminal completion uncapped so the user sees the final state promptly
"""

from __future__ import annotations

import math
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PacsClient.pacs.patient_tab.ui.patient_ui import _vc_progressive as progressive_mod


class _TimerSpy:
    """Minimal single-shot timer spy for progressive grow scheduling."""

    def __init__(self) -> None:
        self.start_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def isActive(self) -> bool:
        return False

    def interval(self) -> int:
        return 150


def _build_storm_controller(
    *,
    admit_batch: int,
    total: int = 120,
    last_grow: int = 20,
    pending: int = 80,
):
    """Build a lightweight controller with the real flush logic bound.

    The per-viewer grow is mocked so we can observe *what the gate decides to
    admit* without pulling in the full VTK/Qt stack.
    """
    ctrl = SimpleNamespace()
    sn = "storm-201"

    ctrl.logger = SimpleNamespace(
        info=lambda *a, **kw: None,
        debug=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        error=lambda *a, **kw: None,
    )
    ctrl._progressive_series = {
        sn: {
            "total": total,
            "last_grow_count": last_grow,
            "last_signal_ms": 0,
            "pending_downloaded": pending,
        }
    }
    ctrl._progressive_display_done = set()
    ctrl._progressive_display_inflight = set()
    ctrl._series_download_completed = set()
    ctrl._progressive_grow_batch_size = 10
    ctrl._progressive_admit_batch_size = admit_batch
    ctrl._is_fast_viewer_mode = lambda: True

    timer = _TimerSpy()
    ctrl._progressive_grow_timer = timer

    viewer = SimpleNamespace(
        _progressive_mode=True,
        _progressive_series_number=sn,
        image_viewer=SimpleNamespace(metadata={"series": {"series_number": sn}}),
    )
    node = SimpleNamespace(vtk_widget=viewer, slider=None)
    ctrl.lst_nodes_viewer = [node]
    ctrl._find_progressive_viewers = lambda s: [(viewer, node)] if s == sn else []

    admitted_visible_counts: list[int] = []
    visible_kwargs: list[int | None] = []

    def _mock_grow(series_number, pending_count, viewers, *, visible_count=None):
        visible = int(pending_count if visible_count is None else visible_count)
        admitted_visible_counts.append(visible)
        visible_kwargs.append(visible_count)
        ctrl._progressive_series[series_number]["last_grow_count"] = visible

    ctrl._grow_progressive_fast = _mock_grow
    ctrl._flush_progressive_grow_impl = types.MethodType(
        progressive_mod._VCProgressiveMixin._flush_progressive_grow_impl,
        ctrl,
    )
    return ctrl, sn, timer, admitted_visible_counts, visible_kwargs


def _drain_nonterminal_burst(ctrl, sn: str, *, max_ticks: int = 100) -> list[int]:
    """Run grow ticks until the non-terminal burst is fully admitted."""
    seq: list[int] = []
    for _ in range(max_ticks):
        info = ctrl._progressive_series[sn]
        if info["last_grow_count"] >= info["pending_downloaded"]:
            break
        before = info["last_grow_count"]
        ctrl._flush_progressive_grow_impl()
        after = ctrl._progressive_series[sn]["last_grow_count"]
        seq.append(after)
        assert after > before, (
            "Storm simulation made no forward progress; this would indicate a "
            f"stuck gate (before={before}, after={after})."
        )
    else:  # pragma: no cover - defensive watchdog
        raise AssertionError("Storm drain exceeded max_ticks; possible runaway complexity")
    return seq


def _metrics(initial_visible: int, admitted_sequence: list[int]) -> dict[str, int | list[int]]:
    """Compute deterministic burst-pressure metrics for a visible-count sequence."""
    deltas = []
    prev = int(initial_visible)
    for current in admitted_sequence:
        deltas.append(int(current) - prev)
        prev = int(current)
    return {
        "deltas": deltas,
        "peak_delta": max(deltas) if deltas else 0,
        "shock_score": sum(d * d for d in deltas),
        "ticks": len(admitted_sequence),
        "final_visible": admitted_sequence[-1] if admitted_sequence else initial_visible,
    }


def _burn_cpu(rounds: int = 250_000) -> int:
    """Deterministic CPU burner used to make the storm harness genuinely hot.

    Local runs are usually near a single-core 90–100% CPU proxy for this loop.
    CI machines vary, so the test that uses this helper asserts only that the
    harness is clearly CPU-bound rather than an exact utilization number.
    """
    acc = 0
    for i in range(rounds):
        acc = (acc + ((i * 17) ^ (i >> 3))) & 0xFFFFFFFF
    return acc


def test_storm_gate_reduces_nonterminal_burst_shock():
    """A gated burst should lower peak per-tick exposure vs the old ungated path.

    This is the core test that answers the user's concern: are we actually
    helping under a storm, or just adding control logic? We compare the same
    burst with and without gating using deterministic pressure proxies.
    """
    initial_visible = 20
    pending = 80

    ungated_ctrl, ungated_sn, _ungated_timer, _u_seq_ref, _u_kwargs = _build_storm_controller(
        admit_batch=10_000,
        last_grow=initial_visible,
        pending=pending,
        total=120,
    )
    gated_ctrl, gated_sn, _gated_timer, _g_seq_ref, _g_kwargs = _build_storm_controller(
        admit_batch=10,
        last_grow=initial_visible,
        pending=pending,
        total=120,
    )

    ungated_seq = _drain_nonterminal_burst(ungated_ctrl, ungated_sn)
    gated_seq = _drain_nonterminal_burst(gated_ctrl, gated_sn)

    ungated = _metrics(initial_visible, ungated_seq)
    gated = _metrics(initial_visible, gated_seq)

    assert ungated_seq == [80], f"Expected old ungated behavior to admit burst at once, got {ungated_seq}"
    assert gated_seq == [30, 40, 50, 60, 70, 80], (
        "Expected gated behavior to admit the 20→80 burst in 10-slice steps, "
        f"got {gated_seq}"
    )
    assert gated["peak_delta"] < ungated["peak_delta"], (
        f"Gate did not reduce peak delta: gated={gated['peak_delta']} ungated={ungated['peak_delta']}"
    )
    assert gated["shock_score"] < ungated["shock_score"], (
        f"Gate did not reduce burst shock score: gated={gated['shock_score']} ungated={ungated['shock_score']}"
    )
    assert gated["final_visible"] == ungated["final_visible"] == pending


def test_storm_gate_adds_only_bounded_background_ticks():
    """The gate may add grow ticks, but the count must stay mathematically bounded."""
    initial_visible = 20
    pending = 120
    admit_batch = 10

    ctrl, sn, timer, _seq_ref, _kwargs = _build_storm_controller(
        admit_batch=admit_batch,
        last_grow=initial_visible,
        pending=pending,
        total=200,  # non-terminal storm; completion not involved here
    )

    admitted_seq = _drain_nonterminal_burst(ctrl, sn)
    expected_ticks = math.ceil((pending - initial_visible) / admit_batch)

    assert len(admitted_seq) == expected_ticks, (
        f"Expected exactly {expected_ticks} bounded drain ticks, got {len(admitted_seq)}: {admitted_seq}"
    )
    assert timer.start_calls == max(0, expected_ticks - 1), (
        "Unexpected timer restart count for bounded storm drain: "
        f"starts={timer.start_calls}, expected={max(0, expected_ticks - 1)}"
    )
    assert admitted_seq[-1] == pending


def test_storm_gate_keeps_terminal_completion_uncapped():
    """Completion remains terminal-authoritative: no slow-drip after total is reached."""
    ctrl, sn, _timer, admitted_seq, visible_kwargs = _build_storm_controller(
        admit_batch=10,
        last_grow=80,
        pending=120,
        total=120,
    )

    ctrl._flush_progressive_grow_impl()

    assert admitted_seq == [120], (
        "Terminal completion must expose the full completed count immediately, "
        f"got {admitted_seq}"
    )
    assert visible_kwargs == [120], (
        "Terminal path must pass the uncapped visible target through the gate, "
        f"got {visible_kwargs}"
    )


def test_storm_harness_reaches_high_cpu_pressure_proxy():
    """The storm harness should be CPU-hot, not just rich in callback count.

    We estimate a single-process CPU pressure proxy using:

        cpu_pct ~= process_time / wall_time * 100

    A local developer machine will usually land near 90–100%. The lower bound
    here is intentionally relaxed so the test stays stable on shared CI agents.
    """
    ctrl, sn, _timer, admitted_seq, _kwargs = _build_storm_controller(
        admit_batch=10,
        last_grow=20,
        pending=120,
        total=180,
    )

    cpu_tokens: list[int] = []

    def _hot_grow(series_number, pending_count, viewers, *, visible_count=None):
        visible = int(pending_count if visible_count is None else visible_count)
        cpu_tokens.append(_burn_cpu())
        admitted_seq.append(visible)
        ctrl._progressive_series[series_number]["last_grow_count"] = visible

    ctrl._grow_progressive_fast = _hot_grow

    wall_t0 = time.perf_counter()
    cpu_t0 = time.process_time()
    drained = _drain_nonterminal_burst(ctrl, sn)
    cpu_pct = ((time.process_time() - cpu_t0) / max(1e-9, time.perf_counter() - wall_t0)) * 100.0

    assert drained == [30, 40, 50, 60, 70, 80, 90, 100, 110, 120], (
        f"Unexpected hot-storm drain sequence: {drained}"
    )
    assert len(cpu_tokens) == len(drained), (
        f"Expected one CPU token per storm tick, got {len(cpu_tokens)} tokens for {len(drained)} ticks"
    )
    assert cpu_pct >= 60.0, (
        "Storm harness was not CPU-heavy enough to represent the intended stress class: "
        f"cpu_pct={cpu_pct:.1f}%"
    )
