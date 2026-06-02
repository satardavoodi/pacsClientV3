"""DM-H4 (orphaned subprocess teardown) + DM-L7 (bounded _tasks) — resource cleanup.

These guard the two resource-harmony fixes applied 2026-06-01:

  DM-H4: WorkerPool._remove_worker must force the child download subprocess to
         exit even when QThread.terminate() bypasses run()'s finally:_cleanup(),
         so the child cannot be orphaned (holding sockets + writing dicom.db).

  DM-L7: the retained-for-retry _tasks dict must be bounded so it cannot grow
         without limit across a long session — never evicting an active study.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from modules.download_manager.workers.download_process_worker import DownloadProcessWorker
from modules.download_manager.workers.worker_pool import WorkerPool
from modules.download_manager.ui.widget._dm_workers import _DMWorkersMixin


# ── DM-H4: ensure_subprocess_dead ────────────────────────────────────────────

# PySide6 forbids object.__new__ on a QThread subclass, so we exercise the
# method logic directly against a stub `self` (it only touches _process /
# _cancel_event). This tests the real ensure_subprocess_dead body unchanged.
def _call_ensure(proc):
    stub = SimpleNamespace(_process=proc, _cancel_event=MagicMock())
    DownloadProcessWorker.ensure_subprocess_dead(stub)
    return stub


def test_ensure_subprocess_dead_terminates_live_child():
    proc = MagicMock()
    proc.is_alive.side_effect = [True, False]  # alive at entry, dead after terminate
    proc.pid = 4321

    stub = _call_ensure(proc)

    assert stub._cancel_event.set.called
    assert proc.terminate.called
    proc.join.assert_called()          # waited for exit
    assert not proc.kill.called        # exited after terminate, no kill needed


def test_ensure_subprocess_dead_kills_if_terminate_ignored():
    proc = MagicMock()
    proc.is_alive.side_effect = [True, True, False]  # survives terminate → escalate
    proc.pid = 4322

    _call_ensure(proc)

    assert proc.terminate.called
    assert proc.kill.called


def test_ensure_subprocess_dead_noop_without_process():
    # must not raise when there is no child process
    _call_ensure(None)


# ── DM-H4: WorkerPool wires the kill into _remove_worker ──────────────────────

def test_remove_worker_force_path_kills_subprocess():
    pool = WorkerPool(max_workers=1)
    worker = MagicMock()
    worker.isRunning.return_value = True
    # wait(3000) → False (won't stop) → force terminate; wait(1000) → True
    worker.wait.side_effect = [False, True]
    wid = "worker-xyz"
    study = "1.2.3.4"
    pool.active_workers[wid] = worker
    pool.worker_by_study[study] = wid

    pool._remove_worker(wid, study)

    # The orphan-prevention call must have fired, and the worker must be gone.
    assert worker.ensure_subprocess_dead.called, (
        "DM-H4: _remove_worker must call worker.ensure_subprocess_dead() so the "
        "child subprocess cannot be orphaned after QThread.terminate()."
    )
    assert wid not in pool.active_workers
    assert study not in pool.worker_by_study


def test_remove_worker_graceful_path_still_ensures_dead():
    # Even when the thread stops gracefully, ensure_subprocess_dead is idempotent
    # and must still be safe to call (belt-and-suspenders).
    pool = WorkerPool(max_workers=1)
    worker = MagicMock()
    worker.isRunning.return_value = True
    worker.wait.return_value = True  # stops on first wait → graceful branch
    wid = "worker-abc"
    pool.active_workers[wid] = worker

    pool._remove_worker(wid, None)

    assert worker.ensure_subprocess_dead.called
    assert wid not in pool.active_workers


# ── DM-L7: _bound_tasks ───────────────────────────────────────────────────────

def _mixin_with_tasks(n: int, active=None):
    m = object.__new__(_DMWorkersMixin)
    m._tasks = {f"s{i:04d}": object() for i in range(n)}  # insertion-ordered
    m._additional_task_info = {f"s{i:04d}": object() for i in range(n)}
    m._series_image_count_cache = {}
    m.worker_pool = SimpleNamespace(worker_by_study=dict(active or {}))
    return m


def test_bound_tasks_evicts_oldest_beyond_cap():
    m = _mixin_with_tasks(405)               # cap is 400
    m._bound_tasks()
    assert len(m._tasks) == 400
    assert "s0000" not in m._tasks            # oldest evicted
    assert "s0404" in m._tasks                # newest retained
    # companion caches reclaimed for the evicted ids
    assert "s0000" not in m._additional_task_info


def test_bound_tasks_never_evicts_active_study():
    # Protect the OLDEST study (the worst case): it must survive, and a
    # different (next-oldest) entry is evicted instead.
    m = _mixin_with_tasks(405, active={"s0000": "worker-1"})
    m._bound_tasks()
    assert len(m._tasks) == 400
    assert "s0000" in m._tasks                # active study protected
    assert "s0001" not in m._tasks            # next-oldest evicted instead


def test_bound_tasks_noop_under_cap():
    m = _mixin_with_tasks(10)
    m._bound_tasks()
    assert len(m._tasks) == 10                # nothing evicted
