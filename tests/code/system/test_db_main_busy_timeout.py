"""Guard: OPT-45 — role-aware ``dicom.db`` busy_timeout.

The shared ``dicom.db`` is WAL, so only a WRITE can block on the write lock — for up to
``busy_timeout``. That ceiling used to be a flat **120 000 ms (2 min)** on EVERY connection, so
a MAIN-process (GUI-thread) write that momentarily contended with the download SUBPROCESS's
instance-write burst could freeze the UI for up to two minutes — the transient "Cross-thread"
Application Hang Windows recorded on the sanam PC (2026-07-28) under a heavy download.

Fix (``database/_pool.py::_resolve_db_timeouts``): the download subprocess (and ANY spawned mp
child) keeps the full 120 s so an instance-write burst never drops a row; the MAIN GUI process
gets a short ceiling (default 5 s) so a contended write fails fast + defers instead of freezing
the UI. Real WAL write-lock holds during a download are sub-second, so 5 s is far longer than any
legitimate contention (writes virtually never raise) — the change only caps the pathological
freeze. Kill switch ``AIPACS_DB_SHORT_MAIN_TIMEOUT=0`` restores the flat 120 s.
"""
import importlib
import os
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "database" / "_pool.py").is_file() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _pool():
    try:
        return importlib.import_module("database._pool")
    except Exception as exc:  # pragma: no cover - import-env dependent
        pytest.skip(f"database._pool import unavailable: {exc}")


@pytest.fixture(autouse=True)
def _clean_env():
    keys = ("AIPACS_DB_ROLE", "AIPACS_DB_SHORT_MAIN_TIMEOUT", "AIPACS_DB_MAIN_BUSY_TIMEOUT_MS")
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    yield
    for k, v in saved.items():
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v


# ── behavioral (drives the REAL _resolve_db_timeouts; the pytest runner is MainProcess) ──

def test_main_process_default_is_short_5s():
    connect_s, busy_ms = _pool()._resolve_db_timeouts()
    assert busy_ms == 5000
    assert connect_s == 5.0


def test_kill_switch_restores_legacy_120s():
    os.environ["AIPACS_DB_SHORT_MAIN_TIMEOUT"] = "0"
    assert _pool()._resolve_db_timeouts() == (300.0, 120000)


def test_main_value_is_tunable_and_clamped():
    m = _pool()
    os.environ["AIPACS_DB_MAIN_BUSY_TIMEOUT_MS"] = "3000"
    assert m._resolve_db_timeouts() == (3.0, 3000)
    os.environ["AIPACS_DB_MAIN_BUSY_TIMEOUT_MS"] = "10"        # below floor
    assert m._resolve_db_timeouts()[1] == 1000
    os.environ["AIPACS_DB_MAIN_BUSY_TIMEOUT_MS"] = "999999"    # above ceiling
    assert m._resolve_db_timeouts()[1] == 120000
    os.environ["AIPACS_DB_MAIN_BUSY_TIMEOUT_MS"] = "not-a-number"
    assert m._resolve_db_timeouts()[1] == 5000                 # bad → default


def test_subprocess_role_marker_keeps_full_120s_and_ignores_tuning():
    # CLINICAL: a writer child must NEVER be throttled (dropping an instance row), even if a
    # (misconfigured) main-tuning env var is inherited.
    os.environ["AIPACS_DB_ROLE"] = "download-subprocess"
    os.environ["AIPACS_DB_MAIN_BUSY_TIMEOUT_MS"] = "3000"
    assert _pool()._resolve_db_timeouts() == (300.0, 120000)


def test_spawned_child_name_alone_keeps_full_120s(monkeypatch):
    # Even WITHOUT the env marker, a spawned mp child (name != "MainProcess") stays at 120 s.
    m = _pool()
    import multiprocessing as mp

    class _FakeProc:
        name = "Process-7"

    monkeypatch.setattr(mp, "current_process", lambda: _FakeProc())
    assert m._resolve_db_timeouts() == (300.0, 120000)


# ── source pins ──

def test_create_connection_consumes_resolved_values():
    src = (_repo_root() / "database" / "_pool.py").read_text(encoding="utf-8")
    assert "connect_timeout_s, busy_timeout_ms = _resolve_db_timeouts()" in src
    assert "timeout=connect_timeout_s," in src
    assert 'f"PRAGMA busy_timeout = {busy_timeout_ms};"' in src
    # the old flat hard-coded ceiling on the connection must be gone
    assert "PRAGMA busy_timeout = 120000" not in src


def test_subprocess_entry_sets_role_marker():
    src = (
        _repo_root() / "modules" / "download_manager" / "workers"
        / "download_process_entry.py"
    ).read_text(encoding="utf-8")
    assert 'os.environ["AIPACS_DB_ROLE"] = "download-subprocess"' in src
