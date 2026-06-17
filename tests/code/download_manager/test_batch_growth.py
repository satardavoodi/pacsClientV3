"""Guards for adaptive batch-size GROWTH (2026-06-16, download speed).

Telemetry showed downloads are round-trip-bound on a healthy connection (~90% of
per-series time is request/response wait, not transfer/disk/decode) while the
batch size only ever SHRANK and was capped at 10 — so a good link kept paying
the overhead of tiny batches. ``_grow_batch_size`` ramps the batch size UP after
consecutive clean batches, bounded by a max; the caller resets the streak on any
shrink (server "Response too large" or the 64 MB byte budget), so it is
self-tuning and safe on a flaky link.

These tests pin the pure ramp/cap/reset arithmetic. ``socket_client`` pulls heavy
deps, so the import is guarded with a skip for minimal environments.
"""

import pytest


def _grow():
    try:
        from modules.download_manager.network.socket_client import _grow_batch_size
    except Exception as exc:  # heavy deps absent in this shard
        pytest.skip(f"socket_client import unavailable: {exc}")
    return _grow_batch_size


def test_no_growth_before_threshold():
    grow = _grow()
    # One clean batch is not enough (growth_after=2): unchanged size, streak carries.
    assert grow(10, 40, 0, 2, 10) == (10, 1)


def test_grows_by_step_and_resets_streak_at_threshold():
    grow = _grow()
    assert grow(10, 40, 1, 2, 10) == (20, 0)


def test_never_exceeds_max():
    grow = _grow()
    assert grow(40, 40, 5, 2, 10) == (40, 6)   # at max → no growth
    assert grow(35, 40, 1, 2, 10) == (40, 0)   # clamps to max, not 45


def test_full_ramp_10_to_40():
    grow = _grow()
    bs, cok, seen = 10, 0, []
    for _ in range(10):
        bs, cok = grow(bs, 40, cok, 2, 10)
        seen.append(bs)
    assert seen[:6] == [10, 20, 20, 30, 30, 40]
    assert max(seen) == 40  # capped


def test_caller_reset_restarts_ramp():
    grow = _grow()
    # Simulate the caller halving + resetting the streak on a shrink, then ramping.
    bs, cok = 20, 0
    bs, cok = grow(bs, 40, cok, 2, 10)
    assert (bs, cok) == (20, 1)  # one clean batch after reset — not yet grown
