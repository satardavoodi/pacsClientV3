"""Reception + assignment data for the patient list must be fetched FAST.

Measured on this center (24 receptions, PACS :8000):

    sequential + a new TCP connection per call .... 1629 ms   (what we shipped)
    8 workers + pooled keep-alive .................  232 ms   (7.0x)

Three things made it slow, all client-side:
  1. ``refresh_assignments`` walked the receptions **sequentially on one thread**;
  2. every REST call used a bare ``requests.get`` → a fresh TCP handshake per call;
  3. a search, the Refresh button and the auto-refresh each re-fetched the WHOLE
     visible list, even one just read.

Pure/offline — no network (the HTTP layer is stubbed).
"""
from __future__ import annotations

import threading
import time

import pytest

from modules.network import http_session as hs
from modules.network import ino_assignment_refresh as refresh


# ── the fan-out ────────────────────────────────────────────────────────────
def test_assignments_are_fetched_in_parallel(monkeypatch, tmp_path):
    """The sequential loop was the bottleneck. The fetches must run CONCURRENTLY.

    Q0 2026-07-14: this used to assert on WALL-CLOCK time (`elapsed < 0.6s`), which is
    unreliable on a loaded parallel test runner — the 8 pool threads compete for CPU with
    the other xdist workers and the 50 ms sleeps stretch past the threshold, so the test
    failed non-deterministically. It now asserts on the property it actually cares about —
    OBSERVED CONCURRENCY: at some instant, more than one fetch was in flight at once. That
    is a direct, timing-robust proof of parallelism (a sequential loop can never exceed 1).
    """
    from modules.network import ino_assignment_server_state as state
    monkeypatch.setattr(state, "_base_dir", lambda: str(tmp_path))
    monkeypatch.setenv("AIPACS_RECEPTION_WORKERS", "8")
    monkeypatch.setenv("AIPACS_ASSIGN_SNAPSHOT_TTL_S", "0")

    _lock = threading.Lock()
    _inflight = 0
    _max_inflight = 0

    def slow(rid):
        nonlocal _inflight, _max_inflight
        with _lock:
            _inflight += 1
            _max_inflight = max(_max_inflight, _inflight)
        try:
            time.sleep(0.05)      # hold the "connection" open so overlap is observable
        finally:
            with _lock:
                _inflight -= 1
        return {"assigned": True, "assignee_name": "Dr X", "assignee_id": "1",
                "assign_type": "radiologist", "assignee_source": "ris_personnel",
                "last_assigned_by": "", "last_assigned_at": "", "mine": False,
                "reception_id": rid}

    monkeypatch.setattr(refresh, "fetch_assignment", slow)
    rids = [str(i) for i in range(24)]

    out = refresh.refresh_assignments(rids)

    assert out["updated"] == 24
    # A sequential loop can never have >1 fetch in flight. Any overlap proves the fan-out.
    # (8 workers ⇒ up to 8; require ≥2 to stay robust even if the pool is starved.)
    assert _max_inflight >= 2, f"fetches are serialised (max concurrency={_max_inflight})"


def test_sequential_mode_is_still_available(monkeypatch, tmp_path):
    from modules.network import ino_assignment_server_state as state
    monkeypatch.setattr(state, "_base_dir", lambda: str(tmp_path))
    monkeypatch.setenv("AIPACS_RECEPTION_WORKERS", "1")
    monkeypatch.setenv("AIPACS_ASSIGN_SNAPSHOT_TTL_S", "0")

    order = []
    monkeypatch.setattr(refresh, "fetch_assignment",
                        lambda rid: (order.append(rid), None)[1])
    refresh.refresh_assignments(["a", "b", "c"])
    assert order == ["a", "b", "c"]


def test_worker_count_is_bounded():
    assert hs.parallel_workers(8) == 8
    assert hs.parallel_workers() >= 1
    import os
    os.environ["AIPACS_RECEPTION_WORKERS"] = "999"
    try:
        assert hs.parallel_workers() <= hs.MAX_WORKERS
    finally:
        del os.environ["AIPACS_RECEPTION_WORKERS"]


# ── don't re-fetch what we just read ───────────────────────────────────────
def test_a_fresh_snapshot_is_not_refetched(monkeypatch, tmp_path):
    from modules.network import ino_assignment_server_state as state
    monkeypatch.setattr(state, "_base_dir", lambda: str(tmp_path))
    monkeypatch.setenv("AIPACS_ASSIGN_SNAPSHOT_TTL_S", "60")

    calls = []
    monkeypatch.setattr(refresh, "fetch_assignment", lambda rid: (
        calls.append(rid),
        {"assigned": False, "assignee_name": "", "assignee_id": "", "assign_type": "",
         "assignee_source": "", "last_assigned_by": "", "last_assigned_at": "",
         "mine": False, "reception_id": rid},
    )[1])

    refresh.refresh_assignments(["50210"])
    assert calls == ["50210"]

    refresh.refresh_assignments(["50210"])          # a second search, same row
    assert calls == ["50210"], "a still-fresh reception must not be re-fetched"


def test_force_always_refetches(monkeypatch, tmp_path):
    """The Refresh button must never serve a cached snapshot."""
    from modules.network import ino_assignment_server_state as state
    monkeypatch.setattr(state, "_base_dir", lambda: str(tmp_path))
    monkeypatch.setenv("AIPACS_ASSIGN_SNAPSHOT_TTL_S", "60")

    calls = []
    monkeypatch.setattr(refresh, "fetch_assignment", lambda rid: (
        calls.append(rid),
        {"assigned": False, "assignee_name": "", "assignee_id": "", "assign_type": "",
         "assignee_source": "", "last_assigned_by": "", "last_assigned_at": "",
         "mine": False, "reception_id": rid},
    )[1])

    refresh.refresh_assignments(["50210"])
    refresh.refresh_assignments(["50210"], force=True)
    assert calls == ["50210", "50210"]


def test_ttl_zero_disables_the_skip(monkeypatch, tmp_path):
    from modules.network import ino_assignment_server_state as state
    monkeypatch.setattr(state, "_base_dir", lambda: str(tmp_path))
    monkeypatch.setenv("AIPACS_ASSIGN_SNAPSHOT_TTL_S", "0")
    calls = []
    monkeypatch.setattr(refresh, "fetch_assignment", lambda rid: (
        calls.append(rid),
        {"assigned": False, "assignee_name": "", "assignee_id": "", "assign_type": "",
         "assignee_source": "", "last_assigned_by": "", "last_assigned_at": "",
         "mine": False, "reception_id": rid},
    )[1])
    refresh.refresh_assignments(["50210"])
    refresh.refresh_assignments(["50210"])
    assert calls == ["50210", "50210"]


# ── connection reuse ───────────────────────────────────────────────────────
def test_sessions_are_pooled_per_base_url():
    hs.reset_sessions()
    a1 = hs.get_session("http://10.0.0.1:8000")
    a2 = hs.get_session("http://10.0.0.1:8000")
    b = hs.get_session("http://10.0.0.2:8000")
    assert a1 is a2, "the same center must reuse ONE connection pool"
    assert a1 is not b, "a different center must get its own pool"
    hs.reset_sessions()


def test_pool_is_at_least_as_large_as_the_worker_count(monkeypatch):
    """A pool smaller than the fan-out would serialise the very calls we just
    parallelised (and log 'Connection pool is full' warnings)."""
    hs.reset_sessions()
    monkeypatch.setenv("AIPACS_RECEPTION_WORKERS", "12")
    sess = hs.get_session("http://10.0.0.9:8000")
    adapter = sess.get_adapter("http://10.0.0.9:8000")
    assert adapter._pool_maxsize >= 12
    hs.reset_sessions()


def test_keepalive_can_be_disabled(monkeypatch):
    hs.reset_sessions()
    monkeypatch.setenv("AIPACS_HTTP_KEEPALIVE", "0")
    assert hs.get_session("http://10.0.0.1:8000") is None
    hs.reset_sessions()


# ── wiring ─────────────────────────────────────────────────────────────────
def _src(*parts) -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[3].joinpath(*parts)).read_text(
        encoding="utf-8", errors="replace")


def test_reception_hydration_uses_the_pooled_session():
    src = _src("PacsClient", "pacs", "workstation_ui", "home_ui", "home_panel", "_hp_search.py")
    block = src.split("def _fetch_reception_patient_payload", 1)[1].split("\n    @", 1)[0]
    assert "http_get" in block
    assert "requests.get(url" not in block


def test_assign_read_uses_the_pooled_session():
    src = _src("modules", "network", "ino_assignment.py")
    block = src.split("def get_assignment", 1)[1].split("\n    def ", 1)[0]
    assert "http_get" in block


def test_reception_hydration_fanout_is_not_hardcoded_to_four():
    src = _src("PacsClient", "pacs", "workstation_ui", "home_ui", "home_panel", "_hp_search.py")
    assert "max_inflight = parallel_workers()" in src


def test_refresh_button_forces_a_reread():
    src = _src("PacsClient", "pacs", "workstation_ui", "home_ui", "patient_table_widget.py")
    body = src.split("def refresh_download_statuses", 1)[1].split("\n    def ", 1)[0]
    assert "_start_assignment_refresh(force=True)" in body
