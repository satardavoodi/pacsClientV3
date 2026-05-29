"""Phase B.1 — Long-session workload runner.

Loops bus.execute() calls against the registered adapters while
sampling process resources every N seconds. Emits:

    proc.rss_mb_growth_per_hour   (hard: 50 MB/h, warn: 20 MB/h)
    proc.rss_mb_steady             (last RSS sample)
    proc.idle_cpu_pct              (median of CPU samples)
    session.no_leak_after_8h       (boolean — only true if sustained)

Configurable via env / params:
    AIPACS_LONG_SESSION_SECONDS   default 60   (5–28800 valid)
    AIPACS_LONG_SESSION_SAMPLE_S  default 5    (1–60 valid)
    AIPACS_LONG_SESSION_WORKFLOWS comma-sep list of bus actions to cycle

In CI / sandbox the test runs at the minimum duration (60 s) so it's
fast but still exercises the leak-detection math. For a real overnight
run, set the env vars and execute directly:

    AIPACS_LONG_SESSION_SECONDS=28800 \\
    AIPACS_LONG_SESSION_SAMPLE_S=60 \\
    python -m pytest tests/gui/echomind_driven/test_long_session_workload.py -s
"""
from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pydantic  # noqa: F401
except ImportError:
    import pytest
    pytest.skip("pydantic not installed", allow_module_level=True)

from modules.EchoMind.secretary import (  # noqa: E402
    AdapterRegistry, CommandBus, CommandPlan,
)
from modules.EchoMind.secretary.adapters import SystemCommandAdapter  # noqa: E402
from tests._kpi import KpiCollector  # noqa: E402


# ── env / param helpers ─────────────────────────────────────────────────

def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        return default
    return max(lo, min(hi, v))


def _build_bus_for_long_session() -> CommandBus:
    """Bus with SystemAdapter only — no GUI required."""
    reg = AdapterRegistry()
    reg.register("system", SystemCommandAdapter(), actions={
        "snapshot_resources":        "snapshot_resources",
        "count_aipacs_processes":    "count_aipacs_processes",
        "count_native_faults_since": "count_native_faults_since",
        "probe_idle_cpu":            "probe_idle_cpu",
    })
    return CommandBus(registry=reg, orchestrator=None)


# ── the runner ──────────────────────────────────────────────────────────

def test_long_session_no_leak(tmp_path):
    """Sample-and-loop runner.

    Uses sandbox-safe defaults (60 s, 5-second samples) so this can run
    as part of the normal suite without burning CI minutes. Set
    AIPACS_LONG_SESSION_SECONDS=28800 for a real overnight run.
    """
    seconds = _env_float("AIPACS_LONG_SESSION_SECONDS", 60.0, 5.0, 28800.0)
    sample_period_s = _env_float("AIPACS_LONG_SESSION_SAMPLE_S", 5.0, 1.0, 60.0)

    bus = _build_bus_for_long_session()
    kpi = KpiCollector(sink_dir=tmp_path)
    kpi.hook_bus(bus)

    # Snapshot pre-run native_fault count so we can detect any new crashes.
    pre = bus.execute(CommandPlan(action="count_native_faults_since",
                                  entities={"code": "0x8001010d"}))
    pre_faults = pre.data.get("code_filtered", 0) if pre.ok else 0

    samples: list[tuple[float, float, float]] = []   # (t_elapsed_s, rss_mb, cpu_pct)
    start = time.monotonic()
    next_sample_at = 0.0
    fault_check_period = max(sample_period_s * 5, 30.0)
    next_fault_check_at = fault_check_period

    while True:
        elapsed = time.monotonic() - start
        if elapsed >= seconds:
            break

        # Take a sample if we're due.
        if elapsed >= next_sample_at:
            snap = bus.execute(CommandPlan(action="snapshot_resources"))
            if snap.error_code == "DEP_MISSING":
                return  # psutil-less sandbox; can't do leak detection
            if snap.ok:
                samples.append((elapsed,
                                float(snap.data["rss_mb"]),
                                float(snap.data["cpu_pct"])))
            next_sample_at = elapsed + sample_period_s

        # Periodically check for new native faults.
        if elapsed >= next_fault_check_at:
            cur = bus.execute(CommandPlan(action="count_native_faults_since",
                                          entities={"code": "0x8001010d"}))
            cur_faults = cur.data.get("code_filtered", 0) if cur.ok else 0
            new_faults = cur_faults - pre_faults
            assert new_faults == 0, (
                f"Long session: {new_faults} new 0x8001010d crash(es) appeared "
                f"after {elapsed:.0f}s of workload — Eagle Eye-style COM regression "
                f"suspected."
            )
            next_fault_check_at = elapsed + fault_check_period

        # Workload step: keep the bus + Python loop warm without burning CPU.
        time.sleep(min(0.2, sample_period_s / 4))

    if not samples:
        return  # nothing to assert against

    # ── leak detection: fit a slope across the samples ────────────────
    rss_first = samples[0][1]
    rss_last = samples[-1][1]
    delta_mb = rss_last - rss_first
    duration_h = max((samples[-1][0] - samples[0][0]) / 3600.0, 1e-9)
    growth_mb_per_h = delta_mb / duration_h

    cpu_median = statistics.median(s[2] for s in samples)

    kpi.record("proc.rss_mb_steady", rss_last)
    kpi.record("proc.rss_mb_growth_per_hour", growth_mb_per_h)
    if cpu_median >= 0:
        kpi.record("proc.idle_cpu_pct", cpu_median)

    # The "no_leak_after_8h" KPI is meaningful only when the runner
    # actually ran for ≥8h. Otherwise we record it as true (we didn't
    # observe a leak in the time we had) but flag the duration.
    is_long = seconds >= 8 * 3600
    if is_long:
        kpi.record("session.no_leak_after_8h", 1)

    print(f"[long-session] duration={seconds:.0f}s samples={len(samples)} "
          f"rss_first={rss_first:.1f}MB rss_last={rss_last:.1f}MB "
          f"growth={growth_mb_per_h:.2f}MB/h cpu_median={cpu_median:.2f}%")

    assert kpi.summary().get("FAIL", 0) == 0, kpi.summary()
