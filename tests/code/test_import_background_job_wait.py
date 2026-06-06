"""Guards for the import background-job wait loop (import-hang fix 2026-06-06).

Root cause (py-spy verified on the live app): _run_background_job_with_progress
used future.add_done_callback(lambda: QTimer.singleShot(0, loop.quit)).  The
done-callback runs in the ThreadPoolExecutor WORKER thread; a QTimer created
there never fires (no Qt event loop in pool threads), so the nested QEventLoop
never quit and the import progress dialog spun forever.  Every further
"Select Folder" click nested another stuck loop (3 deep in the live dump).

These tests pin the fixed behavior:
1. The helper RETURNS for a task slower than the submit→done() race window
   (pre-fix: infinite hang).
2. Exceptions in the task propagate via future.result().
3. _import_folder_with_preview is re-entrancy guarded.
4. Source-level anti-pattern guard: no worker-thread QTimer quit wiring.
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
HP_IMPORT = (
    REPO_ROOT
    / "PacsClient"
    / "pacs"
    / "workstation_ui"
    / "home_ui"
    / "home_panel"
    / "_hp_import.py"
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _HostWidget(QWidget):
    """Minimal host carrying just what _run_background_job_with_progress needs."""

    def __init__(self, pool):
        super().__init__()
        self.thread_pool = pool


def _make_host(qapp):
    from PacsClient.pacs.workstation_ui.home_ui.home_panel._hp_import import (
        _HPImportMixin,
    )

    class Host(_HPImportMixin, _HostWidget):
        pass

    return Host(ThreadPoolExecutor(max_workers=1))


def _with_watchdog(fn, seconds=20.0):
    """Run fn(); if it hangs (regression), kill the process loudly.

    A reintroduced worker-thread-QTimer bug would hang the suite forever;
    os._exit(86) makes the failure visible instead.
    """
    timer = threading.Timer(seconds, os._exit, args=(86,))
    timer.daemon = True
    timer.start()
    try:
        return fn()
    finally:
        timer.cancel()


def test_helper_returns_for_slow_task(qapp):
    """Pre-fix: any task slower than the submit→done() race hung forever."""
    host = _make_host(qapp)

    def slow_task(value):
        time.sleep(0.4)  # well past the future.done() fast-path check
        return value * 2

    result = _with_watchdog(
        lambda: host._run_background_job_with_progress("T", "L", slow_task, 21)
    )
    assert result == 42


def test_helper_returns_for_instant_task(qapp):
    """Fast path (future already done before loop.exec) keeps working."""
    host = _make_host(qapp)
    result = _with_watchdog(
        lambda: host._run_background_job_with_progress("T", "L", lambda: "ok")
    )
    assert result == "ok"


def test_helper_propagates_task_exception(qapp):
    host = _make_host(qapp)

    def boom():
        time.sleep(0.2)
        raise ValueError("scan failed")

    with pytest.raises(ValueError, match="scan failed"):
        _with_watchdog(
            lambda: host._run_background_job_with_progress("T", "L", boom)
        )


def test_import_flow_reentrancy_guard(qapp, monkeypatch):
    """A second call while _import_flow_active must not reach the impl."""
    host = _make_host(qapp)
    calls = []
    monkeypatch.setattr(
        host,
        "_import_folder_with_preview_impl",
        lambda folder: calls.append(folder),
        raising=False,
    )
    # Simulate an in-flight import.
    host._import_flow_active = True
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *a, **k: None)
    )
    host._import_folder_with_preview("X:/nested")
    assert calls == []

    # Released flag → impl runs again, and the flag resets afterwards.
    host._import_flow_active = False
    host._import_folder_with_preview("X:/ok")
    assert calls == ["X:/ok"]
    assert host._import_flow_active is False


def test_source_has_no_worker_thread_quit_wiring():
    """Anti-pattern guard: completion must never be signalled from the worker
    thread via QTimer (add_done_callback runs in the pool thread)."""
    src = HP_IMPORT.read_text(encoding="utf-8")
    assert "add_done_callback(lambda _f: QTimer.singleShot" not in src
    # The main-thread poll timer must remain.
    assert "poll = QTimer(progress)" in src
    assert "poll.start()" in src
