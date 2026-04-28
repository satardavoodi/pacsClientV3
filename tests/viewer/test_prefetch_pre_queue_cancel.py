"""F3.1 — Pre-queue cancellation gates in `Lightweight2DPipeline._submit_prefetch`.

Verifies that stale prefetch tasks are rejected BEFORE `executor.submit`,
so they never burn IPC + pickle + worker dispatch cost. Three gates:

  1. Generation gate     — `generation > 0 and generation != _prefetch_generation`
  2. Request-epoch gate  — `request_epoch > 0 and request_epoch != _prefetch_request_epoch
                            and idx not in _active_prefetch_targets`
  3. Distance gate       — `abs(idx - _current_index) > _max_distance`
                           (`_max_distance = 6` if `_fast_interaction` else
                            `_config.prefetch_radius`)

Each rejection increments `PerfMetrics.cancelled_task` and the executor
must NOT be touched.

Post-decode guards in `_decode_into_cache` remain intact as a safety net
and are NOT exercised by these tests.
"""

from __future__ import annotations

import threading
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _enable_perf_metrics():
    """PerfMetrics is opt-in; enable+reset for each test so counters move."""
    from modules.viewer.fast.lightweight_2d_pipeline import PerfMetrics
    pm = PerfMetrics.get()
    pm.enable()
    pm.reset()
    yield
    pm.disable()


def _build_pipeline_with_real_submit(
    *,
    generation: int = 0,
    request_epoch: int = 0,
    active_targets: set[int] | None = None,
    current_index: int = 50,
    fast_interaction: bool = False,
    radius: int = 3,
):
    """Construct a stub bound to the real `_submit_prefetch` from the pipeline."""
    from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline

    p = SimpleNamespace()
    p._prefetch_lock = threading.Lock()
    p._prefetch_pending = set()
    p._pixel_cache = {}
    p._prefetch_generation = generation
    p._prefetch_request_epoch = request_epoch
    p._active_prefetch_targets = set(active_targets or set())
    p._current_index = current_index
    p._fast_interaction = fast_interaction
    p._config = SimpleNamespace(prefetch_radius=radius)
    p._protected_drag_active = False
    p._drag_session_token = 0
    p._drag_prefetch_submitted = 0
    # _decode_into_cache is referenced by `executor.submit(self._decode_into_cache, ...)`
    # in the admit path; the MagicMock executor never invokes it, but Python
    # still resolves the attribute, so a stub is required.
    p._decode_into_cache = MagicMock()

    # The real method must NOT reach this executor when the gates fire.
    p._decode_executor = MagicMock()
    p._decode_executor.submit = MagicMock()

    p._submit_prefetch = types.MethodType(
        Lightweight2DPipeline._submit_prefetch, p
    )
    return p


def _cancelled_count():
    from modules.viewer.fast.lightweight_2d_pipeline import PerfMetrics
    return int(PerfMetrics.get()._cancelled_tasks)


def _submitted_count():
    from modules.viewer.fast.lightweight_2d_pipeline import PerfMetrics
    return int(PerfMetrics.get()._prefetch_submitted)


# ---------------------------------------------------------------------------
# Generation gate
# ---------------------------------------------------------------------------

class TestGenerationGate:
    def test_stale_generation_rejected_pre_queue(self):
        p = _build_pipeline_with_real_submit(generation=5)
        before_cancelled = _cancelled_count()
        before_submitted = _submitted_count()

        # Caller passes stale generation=3, current is 5 → reject.
        p._submit_prefetch(50, generation=3, request_epoch=0)

        assert p._decode_executor.submit.call_count == 0, \
            "Stale generation must NOT reach executor.submit"
        assert 50 not in p._prefetch_pending, \
            "Rejected idx must not be added to pending set"
        assert _cancelled_count() == before_cancelled + 1
        assert _submitted_count() == before_submitted, \
            "Pre-queue rejection must NOT increment prefetch_submitted"

    def test_zero_generation_skips_gate(self):
        # generation=0 means caller did not supply a generation token; gate
        # must not fire.  The other two gates may still fire, so use a
        # geometry that satisfies them.
        p = _build_pipeline_with_real_submit(
            generation=5, current_index=50, radius=3
        )

        p._submit_prefetch(50, generation=0, request_epoch=0)

        # idx 50 == current_index, dedup-blocked? No: pixel_cache empty,
        # pending empty.  Should reach executor.
        assert p._decode_executor.submit.call_count == 1
        assert 50 in p._prefetch_pending

    def test_matching_generation_admits(self):
        p = _build_pipeline_with_real_submit(
            generation=5, current_index=50, radius=3
        )

        p._submit_prefetch(51, generation=5, request_epoch=0)

        assert p._decode_executor.submit.call_count == 1
        assert 51 in p._prefetch_pending


# ---------------------------------------------------------------------------
# Request-epoch gate
# ---------------------------------------------------------------------------

class TestRequestEpochGate:
    def test_stale_epoch_without_active_target_rejected(self):
        p = _build_pipeline_with_real_submit(
            generation=0,
            request_epoch=10,
            active_targets={48, 49, 51, 52},
            current_index=50,
            radius=3,
        )
        before_cancelled = _cancelled_count()

        # idx 53 is NOT in active targets, request_epoch 7 != current 10.
        p._submit_prefetch(53, generation=0, request_epoch=7)

        assert p._decode_executor.submit.call_count == 0
        assert _cancelled_count() == before_cancelled + 1

    def test_stale_epoch_with_active_target_admits(self):
        # If the idx is in active targets, the stale-epoch gate must NOT fire
        # (matches existing _decode_into_cache behavior).
        p = _build_pipeline_with_real_submit(
            generation=0,
            request_epoch=10,
            active_targets={51},
            current_index=50,
            radius=3,
        )

        p._submit_prefetch(51, generation=0, request_epoch=7)

        assert p._decode_executor.submit.call_count == 1
        assert 51 in p._prefetch_pending


# ---------------------------------------------------------------------------
# Distance gate
# ---------------------------------------------------------------------------

class TestDistanceGate:
    def test_idle_uses_config_radius(self):
        p = _build_pipeline_with_real_submit(
            current_index=50, fast_interaction=False, radius=3
        )
        before_cancelled = _cancelled_count()

        # |60 - 50| = 10 > 3 → reject.
        p._submit_prefetch(60, generation=0, request_epoch=0)

        assert p._decode_executor.submit.call_count == 0
        assert _cancelled_count() == before_cancelled + 1

    def test_fast_interaction_uses_distance_6(self):
        # Fast-interaction slack window per existing _decode_into_cache code.
        p = _build_pipeline_with_real_submit(
            current_index=50, fast_interaction=True, radius=3
        )

        # |56 - 50| = 6 → still admitted (boundary).
        p._submit_prefetch(56, generation=0, request_epoch=0)
        assert p._decode_executor.submit.call_count == 1

    def test_fast_interaction_distance_7_rejected(self):
        p = _build_pipeline_with_real_submit(
            current_index=50, fast_interaction=True, radius=3
        )
        before_cancelled = _cancelled_count()

        # |57 - 50| = 7 > 6 → reject.
        p._submit_prefetch(57, generation=0, request_epoch=0)

        assert p._decode_executor.submit.call_count == 0
        assert _cancelled_count() == before_cancelled + 1


# ---------------------------------------------------------------------------
# Combined: pre-queue gates short-circuit before dedup checks
# ---------------------------------------------------------------------------

class TestPreQueueOrdering:
    def test_stale_generation_does_not_pollute_pending_set(self):
        p = _build_pipeline_with_real_submit(generation=5, current_index=50)
        # Pre-populate something to make sure stale rejection does not touch.
        p._prefetch_pending.add(99)

        p._submit_prefetch(50, generation=3, request_epoch=0)

        assert p._prefetch_pending == {99}, \
            "Pre-queue rejection must not mutate _prefetch_pending"
        assert p._decode_executor.submit.call_count == 0
