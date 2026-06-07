"""Guards for the shared retry-I/O worker (heavy-CT GUI freeze fix).

py-spy on the live app (2026-06-07 stress): the GUI thread wedged >283 s
INSIDE ``threading.Thread.start()`` called from ``_dm_retry._on_series_retry``
— under heavy load new threads could not bootstrap, and start() blocks until
the child signals started. Fix: retry/cleanup I/O is queued onto ONE shared
daemon worker (pre-warmed at DM widget init); submission is a queue put, not
a thread spawn.
"""

import threading
import time
from pathlib import Path

from modules.download_manager.ui.widget import _dm_retry as R

SRC_DIR = Path(__file__).resolve().parents[3] / "modules" / "download_manager" / "ui" / "widget"


def test_no_inline_thread_spawn_left_in_retry_paths():
    src = (SRC_DIR / "_dm_retry.py").read_text(encoding="utf-8", errors="ignore")
    # The ONLY Thread( construction allowed is inside ensure_retry_bg_worker.
    ensure_at = src.index("def ensure_retry_bg_worker")
    next_def = src.index("def _retry_bg_submit")
    outside = src[:ensure_at] + src[next_def:]
    assert "threading.Thread(" not in outside
    # All three legacy spawn sites must now submit to the shared worker.
    assert outside.count("_retry_bg_submit(") >= 3


def test_widget_prewarms_worker_at_init():
    src = (SRC_DIR / "widget.py").read_text(encoding="utf-8", errors="ignore")
    assert "ensure_retry_bg_worker()" in src


def test_submit_is_nonblocking_and_jobs_run():
    R.ensure_retry_bg_worker()
    done = threading.Event()
    slow_started = threading.Event()

    def slow():
        slow_started.set()
        time.sleep(0.5)

    def fast():
        done.set()

    R._retry_bg_submit(slow)
    assert slow_started.wait(2.0)
    # Submitting while the worker is BUSY must return immediately (queue put).
    t0 = time.perf_counter()
    R._retry_bg_submit(fast)
    submit_ms = (time.perf_counter() - t0) * 1000
    assert submit_ms < 50, f"submit blocked {submit_ms:.1f} ms"
    assert done.wait(3.0)  # runs after the slow job finishes


def test_worker_survives_job_exception():
    R.ensure_retry_bg_worker()
    ok = threading.Event()

    def boom():
        raise RuntimeError("job failed")

    R._retry_bg_submit(boom)
    R._retry_bg_submit(ok.set)
    assert ok.wait(3.0)
    assert R._RETRY_BG_WORKER.is_alive()


def test_snapshot_resources_hardened():
    src = (
        Path(__file__).resolve().parents[3]
        / "modules" / "EchoMind" / "secretary" / "adapters" / "system_command_adapter.py"
    ).read_text(encoding="utf-8", errors="ignore")
    assert "cpu_percent(interval=None)" in src
    assert "include_open_files" in src
    assert "cpu_percent(interval=0.1)" not in src
