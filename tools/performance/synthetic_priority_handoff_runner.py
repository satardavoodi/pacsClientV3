"""F3.5.2 — Synthetic priority-handoff headless runner.

Drives the DM ``SeriesIntentCoordinator`` priority-handoff retry chain
without Qt timers or a real download pipeline. Captures all
``[INTENT_PRIORITY]`` log emissions and parses them through the existing
KPI harness (``parse_priority_handoff_log_text``). Produces two JSON
baselines:

  - ``priority_handoff_v2_pre.json``  — env=0 (legacy 90 + 3 chain).
  - ``priority_handoff_v2_post.json`` — env=1 (V2 wall-clock budget).

Scenario per F3.5.2 plan:
  - 20 simulated drag-drop CRITICAL promotions.
  - On each promotion, the worker pool is "busy" for the first 25 s of
    virtual time, then "free" — modelling a peer worker that holds its
    slot for ~25 s before releasing.
  - The reclamation race is also exercised: 3 of the 20 promotions are
    flagged ``can_add_worker==True but start_download_worker==False`` for
    the first 1 s, then both succeed — modelling a dying worker whose
    slot is reported free before the rule engine is ready to start.

Limitations:
  - All time is *virtual*. We do not call ``time.sleep`` or run a Qt
    event loop. The defer queue is a min-heap keyed by virtual ms.
  - ``time.monotonic`` is NOT monkeypatched; the coordinator's
    ``_priority_retry_started_ms`` records real wall-clock time. We
    rewind it to the virtual baseline before each tick to reproduce a
    deterministic ``elapsed_ms`` field. The KPI parser sees stable
    numbers across runs.
  - This runner does not exercise real socket I/O, real worker pool
    threading, or real DM observer fan-out. It is a pure
    coordinator-state-machine driver.

Plan reference: F3.5.2.
"""
from __future__ import annotations

import argparse
import heapq
import io
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Late imports (after sys.path) — must happen before logging configuration so
# the coordinator's logger name is registered.
from modules.download_manager.coordinator.series_intent_coordinator import (  # noqa: E402
    SeriesIntentCoordinator,
)
from modules.download_manager.coordinator import series_intent_coordinator as sic_module  # noqa: E402
from modules.download_manager.core.enums import DownloadPriority, DownloadStatus  # noqa: E402
from modules.download_manager.core.models import DownloadTask  # noqa: E402
from modules.download_manager.state.state_store import DownloadStateStore  # noqa: E402
from tools.performance.clearcanvas_aipacs_kpi_harness import (  # noqa: E402
    parse_priority_handoff_log_text,
)


# ── Virtual-time defer queue ────────────────────────────────────────────────

class _VirtualClock:
    """Min-heap of (virtual_ms, sequence, callback) tuples."""

    def __init__(self) -> None:
        self._now_ms: float = 0.0
        self._heap: List[Tuple[float, int, Callable[[], None]]] = []
        self._seq = 0

    def now_ms(self) -> float:
        return self._now_ms

    def schedule(self, delay_ms: int, cb: Callable[[], None]) -> None:
        self._seq += 1
        heapq.heappush(self._heap, (self._now_ms + float(delay_ms), self._seq, cb))

    def advance_to_next(self) -> bool:
        if not self._heap:
            return False
        when, _seq, cb = heapq.heappop(self._heap)
        self._now_ms = when
        try:
            cb()
        except Exception:  # noqa: BLE001
            pass
        return True

    def drain(self, max_ticks: int = 100_000) -> int:
        """Drain the queue. Returns number of ticks fired."""
        n = 0
        while self.advance_to_next() and n < max_ticks:
            n += 1
        return n


# ── Worker-pool stub modelling the 25 s busy window ─────────────────────────

class _SimPool:
    """Worker pool that is `busy` until `release_at_ms`, then `free`."""

    max_workers = 1
    active_workers = {"peer": 1}

    def __init__(self, clock: _VirtualClock, release_at_ms: float) -> None:
        self._clock = clock
        self._release_at_ms = release_at_ms

    def can_add_worker(self) -> bool:
        if self._clock.now_ms() >= self._release_at_ms:
            self.active_workers = {}
            return True
        self.active_workers = {"peer": 1}
        return False


class _SimRuleEngine:
    def evaluate_preemption(self, _task):
        return None


# ── Started-ms rewriter so elapsed_ms == virtual ms (deterministic) ─────────

class _StartedMsRewriter:
    """Patches `coordinator._priority_retry_started_ms` so that
    ``int((time.monotonic() - started_ms) * 1000) == virtual_now_ms``.

    Without this, real wall-clock time leaks into the elapsed_ms emit
    (because the coordinator stores `time.monotonic()` internally), making
    the synthetic baseline non-deterministic.
    """

    def __init__(self, coordinator: SeriesIntentCoordinator, clock: _VirtualClock) -> None:
        self.coord = coordinator
        self.clock = clock

    def sync(self, study_uid: str) -> None:
        if study_uid not in self.coord._priority_retry_started_ms:
            return
        # Set started_ms = real_monotonic_now - virtual_ms_elapsed/1000.
        self.coord._priority_retry_started_ms[study_uid] = (
            time.monotonic() - (self.clock.now_ms() / 1000.0)
        )


# ── Single drag-drop scenario ───────────────────────────────────────────────

def _run_one_handoff(
    study_uid: str,
    *,
    release_at_ms: float,
    reclamation_window_ms: float,
    log_capture: logging.Handler,
) -> None:
    clock = _VirtualClock()
    pool = _SimPool(clock, release_at_ms=release_at_ms)
    state_store = DownloadStateStore()
    task = DownloadTask(
        study_uid=study_uid,
        patient_id="p1",
        patient_name="Synthetic^Handoff",
        study_date="2026-04-29",
        study_time="08:30:00",
        modality="CT",
        description="Synthetic handoff",
        series_list=[],
        priority=DownloadPriority.CRITICAL,
        output_dir=Path("."),
    )
    state_store.create(task)
    state_store.update(study_uid, status=DownloadStatus.PENDING)

    rewriter: Optional[_StartedMsRewriter] = None  # populated after coord built

    def _start_download_worker(uid: str) -> bool:
        # Reclamation race: in the first reclamation_window_ms of virtual
        # time AFTER the peer worker released its slot, even a "free" pool
        # refuses to start (modelling the dying-worker / rule-engine
        # ordering window). After that, start always succeeds.
        if pool.can_add_worker():
            ms_since_release = clock.now_ms() - release_at_ms
            if 0 <= ms_since_release < reclamation_window_ms:
                return False
            return True
        return False

    coordinator = SeriesIntentCoordinator(
        state_store=state_store,
        rule_engine=_SimRuleEngine(),
        worker_pool=pool,
        tasks_ref={study_uid: task},
        pause_downloads_for_preemption=lambda _uids: None,
        start_download_worker=_start_download_worker,
        start_next_pending=lambda: None,
        refresh_table_order=lambda: None,
        check_auto_resume=lambda: None,
        defer_call=lambda d, cb: clock.schedule(d, cb),
    )
    rewriter = _StartedMsRewriter(coordinator, clock)

    # Wrap the coordinator's emit so each emit happens AFTER we sync the
    # started_ms to the virtual clock. This ensures elapsed_ms in the log
    # tracks virtual time.
    real_emit = coordinator._emit_intent_priority

    def _emit_synced(*args, **kwargs):
        rewriter.sync(study_uid)
        return real_emit(*args, **kwargs)

    coordinator._emit_intent_priority = _emit_synced  # type: ignore[assignment]

    coordinator.schedule_priority_start_retry(study_uid)
    # Drain virtual time up to a safety budget of 90 s + slack.
    safety_budget_ms = 90_000.0
    while clock.now_ms() < safety_budget_ms:
        if not clock.advance_to_next():
            break
        # Stop early if chain cleared.
        if study_uid not in coordinator._priority_retry_tokens:
            break


# ── Top-level driver ────────────────────────────────────────────────────────

def _run_scenario(env_value: str, n_handoffs: int = 20) -> Dict[str, Any]:
    """Run `n_handoffs` simulated drag-drop CRITICAL promotions and parse the log."""
    os.environ["AIPACS_INTENT_HANDOFF_V2"] = env_value
    # Force trace=True so every defer / tick is captured for the parser.
    sic_module._INTENT_TRACE_ENABLED = True

    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)
    target_logger = logging.getLogger(sic_module.__name__)
    saved_level = target_logger.level
    target_logger.setLevel(logging.INFO)
    target_logger.addHandler(handler)
    saved_propagate = target_logger.propagate
    target_logger.propagate = False

    try:
        wall_started = time.perf_counter()
        for i in range(n_handoffs):
            # 3 of 20 exercise the reclamation race for the first 1 s.
            reclamation_window = 1000.0 if i in (3, 9, 15) else 0.0
            _run_one_handoff(
                study_uid=f"study-handoff-{i:03d}",
                release_at_ms=25_000.0,  # peer worker releases at 25 s
                reclamation_window_ms=reclamation_window,
                log_capture=handler,
            )
        wall_elapsed_s = time.perf_counter() - wall_started
    finally:
        target_logger.removeHandler(handler)
        target_logger.setLevel(saved_level)
        target_logger.propagate = saved_propagate
        sic_module._INTENT_TRACE_ENABLED = (
            os.environ.get("AIPACS_INTENT_PRIORITY_TRACE", "0") == "1"
        )

    log_text = buffer.getvalue()
    metrics = parse_priority_handoff_log_text(log_text)
    metrics["env_AIPACS_INTENT_HANDOFF_V2"] = env_value
    metrics["n_handoffs"] = n_handoffs
    metrics["runner_wall_elapsed_s"] = round(wall_elapsed_s, 3)
    return {
        "viewer": "AI-PACS",
        "mode": "priority-handoff-synthetic",
        "scenario": "aipacs_dm_priority_handoff_synthetic",
        "env_AIPACS_INTENT_HANDOFF_V2": env_value,
        "n_handoffs": n_handoffs,
        "priority_handoff_metrics": metrics,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_PROJECT_ROOT / "generated-files" / "benchmarks",
        help="Output directory for the JSON baselines.",
    )
    parser.add_argument(
        "--n-handoffs",
        type=int,
        default=20,
        help="Number of simulated drag-drop CRITICAL promotions.",
    )
    parser.add_argument(
        "--mode",
        choices=("pre", "post", "both"),
        default="both",
        help="Which baseline(s) to produce.",
    )
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    results: Dict[str, Path] = {}
    if args.mode in ("pre", "both"):
        pre = _run_scenario("0", n_handoffs=args.n_handoffs)
        out = args.out_dir / "priority_handoff_v2_pre.json"
        out.write_text(json.dumps(pre, indent=2), encoding="utf-8")
        results["pre"] = out
        print(f"[runner] wrote {out}")
    if args.mode in ("post", "both"):
        post = _run_scenario("1", n_handoffs=args.n_handoffs)
        out = args.out_dir / "priority_handoff_v2_post.json"
        out.write_text(json.dumps(post, indent=2), encoding="utf-8")
        results["post"] = out
        print(f"[runner] wrote {out}")

    if args.mode == "both":
        # Print a concise comparison line for quick triage.
        pre_p95 = pre["priority_handoff_metrics"]["overlap_priority_handoff_latency_p95_ms"]
        post_p95 = post["priority_handoff_metrics"]["overlap_priority_handoff_latency_p95_ms"]
        pre_recovery = pre["priority_handoff_metrics"]["recovery_exhaust_count"]
        post_recovery = post["priority_handoff_metrics"]["recovery_exhaust_count"]
        post_v2_total = post["priority_handoff_metrics"]["overlap_priority_handoff_v2_total_exhaust_count"]
        print(
            f"[runner] p95_ms pre={pre_p95} post={post_p95} | "
            f"recovery_exhaust pre={pre_recovery} post={post_recovery} | "
            f"v2_total_exhaust={post_v2_total}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
