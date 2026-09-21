"""Tests for deferred (worker-thread) folder-size refresh in
StorageCleanupPanelWidget.

Regression target: 2026-04-29 G6 stall analysis showed
StorageCleanupPanelWidget.__init__ blocked the main thread for 100ms-2s+
because it ran a synchronous recursive `rglob("*") + stat()` over patient,
education, cache, and offline-cloud roots inside the constructor.

Contract:
- Panel constructor MUST NOT call get_folder_usage_breakdown synchronously.
- The first folder-size refresh MUST be issued via a QThread worker.
- A second refresh request while one is in flight MUST be coalesced and
  re-issued exactly once when the running worker finishes.
"""
from __future__ import annotations

import os
import sys
import time
import threading
from types import SimpleNamespace

import pytest

# Headless Qt setup BEFORE importing PySide6 widgets.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


# Repository root on sys.path for imports
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app
    from PacsClient.pacs.workstation_ui.settings_ui import storage_cleanup_panel as scp

    deadline = time.monotonic() + 6.0
    for thread in list(scp._ACTIVE_STORAGE_JOBS):
        if thread.isRunning():
            thread.quit()
    while scp._ACTIVE_STORAGE_JOBS and time.monotonic() < deadline:
        QCoreApplication.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(0.01)
    assert not scp._ACTIVE_STORAGE_JOBS


def _process_until(predicate, timeout_ms: int = 3000):
    """Spin the Qt event loop until predicate() returns True or timeout."""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        QCoreApplication.processEvents(QEventLoop.AllEvents, 50)
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class _FakeManager:
    """Stand-in for LocalStorageCleanupManager that records call timing."""

    def __init__(self, work_seconds: float = 0.05, sizes: dict | None = None):
        self.work_seconds = float(work_seconds)
        self.sizes = sizes or {"patients": 100, "education": 200, "cache": 300, "printing": 400}
        self.calls = []  # list of (thread_ident, force_refresh, t_start)
        self.drive_calls = []
        self.preview_calls = []
        self.consistency_calls = []
        self._lock = threading.Lock()

    # -- subset of LocalStorageCleanupManager API used by the panel --
    def get_drive_usage_info(self):
        self.drive_calls.append(threading.get_ident())
        return [{"drive": "C:\\", "used": 1000, "total": 2000, "free": 1000, "used_percent": 50.0}]

    def get_folder_usage_breakdown(self, force_refresh: bool = False):
        with self._lock:
            self.calls.append((threading.get_ident(), bool(force_refresh), time.monotonic()))
        # Simulate a real disk walk taking measurable time.
        time.sleep(self.work_seconds)
        return dict(self.sizes)

    def get_folder_map(self):
        return {
            "patients": [],
            "education": [],
            "cache": [],
            "printing": [],
        }

    def build_patient_cleanup_preview(self, strategy, value):
        self.preview_calls.append(threading.get_ident())
        return {
            "strategy": strategy,
            "value": value,
            "total_patients": 3,
            "selected_patients": 1,
            "kept_patients": 2,
            "unknown_date_patients": 0,
            "estimated_bytes": 100,
            "invalid_paths": 0,
        }

    def validate_storage_consistency(self):
        self.consistency_calls.append(threading.get_ident())
        return {
            "counts": {
                "db_studies": 1,
                "db_studies_missing_files": 0,
                "orphan_disk_studies": 0,
                "thumbnails_missing_source": 0,
            }
        }

    @staticmethod
    def format_size(n: int) -> str:
        return f"{int(n)} B"


def _build_panel_with_fake_manager(qapp, fake_manager):
    """Construct StorageCleanupPanelWidget but inject a fake manager BEFORE
    __init__ runs the deferred refresh."""
    from PacsClient.pacs.workstation_ui.settings_ui import storage_cleanup_panel as scp

    real_cls = scp.LocalStorageCleanupManager

    # Patch the class so the constructor inside the panel returns our fake.
    scp.LocalStorageCleanupManager = lambda *a, **kw: fake_manager  # type: ignore[assignment]
    try:
        panel = scp.StorageCleanupPanelWidget()
    finally:
        scp.LocalStorageCleanupManager = real_cls
    return panel


def test_constructor_does_not_block_on_folder_walk(qapp):
    """Panel construction must return promptly even when the heavy walk is slow.

    Contract: the heavy `get_folder_usage_breakdown` call MUST NOT add to
    constructor time. Qt widget allocation has its own non-trivial cost
    (especially in offscreen mode on first invocation), so we test that
    construction time is *substantially* less than the simulated walk —
    proving the walk runs off the main thread.
    """
    from PacsClient.pacs.workstation_ui.settings_ui import storage_cleanup_panel as scp  # noqa: F401

    walk_seconds = 3.0  # Long enough to dwarf any Qt setup cost.
    fake = _FakeManager(work_seconds=walk_seconds)
    t0 = time.monotonic()
    panel = _build_panel_with_fake_manager(qapp, fake)
    elapsed = time.monotonic() - t0
    try:
        # Construction must finish well before the walk would have completed.
        # If the walk were synchronous, ctor would take >= walk_seconds.
        assert elapsed < (walk_seconds - 1.0), (
            f"Panel construction took {elapsed*1000:.1f}ms; folder walk "
            f"({walk_seconds}s) appears to be running synchronously."
        )
        # A worker thread must have been started (or already finished — both ok).
        # If not started, no folder breakdown call would have happened.
        # Wait for the worker to finish.
        assert _process_until(lambda: len(fake.calls) >= 1, timeout_ms=int(walk_seconds * 1000) + 4000), (
            "Worker did not call get_folder_usage_breakdown within timeout"
        )
        # The breakdown must have been computed off the main (test) thread.
        main_tid = threading.get_ident()
        worker_tids = {tid for tid, _force, _t in fake.calls}
        assert main_tid not in worker_tids, (
            f"get_folder_usage_breakdown ran on main thread {main_tid}; calls={fake.calls}"
        )
        assert fake.drive_calls and main_tid not in set(fake.drive_calls)
    finally:
        panel.deleteLater()
        QCoreApplication.processEvents()


def test_concurrent_refresh_is_coalesced(qapp):
    """Issuing a refresh while one is in flight must coalesce, then run once more."""
    fake = _FakeManager(work_seconds=0.3)
    panel = _build_panel_with_fake_manager(qapp, fake)
    try:
        # Wait for initial worker to start (one call queued or running).
        assert _process_until(lambda: len(fake.calls) >= 1 or panel._folder_size_thread is not None, timeout_ms=2000)

        # While the initial worker is still running, request several refreshes.
        for _ in range(5):
            panel.refresh_storage_insights(force_refresh=True, defer_folder_sizes=True)

        # Wait for everything to settle (both initial + one coalesced follow-up).
        assert _process_until(
            lambda: panel._folder_size_thread is None and len(fake.calls) >= 2,
            timeout_ms=5000,
        ), f"Did not settle. calls={len(fake.calls)} thread={panel._folder_size_thread}"

        # Exactly TWO calls total: 1 initial + 1 coalesced follow-up. Not 6.
        assert len(fake.calls) == 2, (
            f"Expected coalesced follow-up (=2 calls), got {len(fake.calls)}"
        )
    finally:
        panel.deleteLater()
        QCoreApplication.processEvents()


def test_defer_folder_sizes_false_runs_sync(qapp):
    """Backwards compat: explicit defer_folder_sizes=False keeps sync semantics."""
    fake = _FakeManager(work_seconds=0.0)  # instant
    panel = _build_panel_with_fake_manager(qapp, fake)
    try:
        # Drain initial deferred refresh.
        assert _process_until(lambda: panel._folder_size_thread is None, timeout_ms=3000)
        baseline_calls = len(fake.calls)

        # Now call with defer=False; must run synchronously on main thread.
        main_tid = threading.get_ident()
        panel.refresh_storage_insights(force_refresh=True, defer_folder_sizes=False)
        # The most recent call should be on the main thread.
        assert len(fake.calls) == baseline_calls + 1
        latest_tid = fake.calls[-1][0]
        assert latest_tid == main_tid, (
            f"defer=False should run sync on main; got tid {latest_tid} vs main {main_tid}"
        )
    finally:
        panel.deleteLater()
        QCoreApplication.processEvents()


def test_cleanup_completion_callback_is_marshaled_to_gui_thread(qapp):
    fake = _FakeManager(work_seconds=0.0)
    panel = _build_panel_with_fake_manager(qapp, fake)
    try:
        assert _process_until(lambda: panel._folder_size_thread is None, timeout_ms=3000)
        main_tid = threading.get_ident()
        callbacks = []
        result = SimpleNamespace(success=True, warnings=[])

        panel._run_cleanup_job(
            panel,
            lambda: result,
            on_done=lambda _parent, value: callbacks.append(
                (threading.get_ident(), value)
            ),
            on_fail=lambda _parent, message: callbacks.append(
                (threading.get_ident(), message)
            ),
        )

        assert _process_until(lambda: bool(callbacks), timeout_ms=3000)
        assert callbacks == [(main_tid, result)]
        assert _process_until(lambda: panel._cleanup_thread is None, timeout_ms=3000)
    finally:
        panel.deleteLater()
        QCoreApplication.processEvents()


def test_cleanup_thread_is_not_owned_by_transient_panel(qapp):
    fake = _FakeManager(work_seconds=0.0)
    panel = _build_panel_with_fake_manager(qapp, fake)
    release = threading.Event()
    try:
        assert _process_until(lambda: panel._folder_size_thread is None, timeout_ms=3000)

        panel._run_cleanup_job(
            panel,
            lambda: (release.wait(2.0), SimpleNamespace(success=True, warnings=[]))[1],
            on_done=lambda *_args: None,
            on_fail=lambda *_args: None,
        )

        assert _process_until(lambda: panel._cleanup_thread is not None, timeout_ms=1000)
        assert panel._cleanup_thread.parent() is None
    finally:
        release.set()
        _process_until(lambda: panel._cleanup_thread is None, timeout_ms=3000)
        panel.deleteLater()
        QCoreApplication.processEvents()


def test_preview_and_consistency_disk_work_are_not_on_gui_thread(qapp, monkeypatch):
    from PacsClient.pacs.workstation_ui.settings_ui import storage_cleanup_panel as scp

    fake = _FakeManager(work_seconds=0.0)
    panel = _build_panel_with_fake_manager(qapp, fake)
    shown = []
    monkeypatch.setattr(scp.QMessageBox, "information", lambda *args: shown.append(args))
    try:
        assert _process_until(lambda: panel._folder_size_thread is None, timeout_ms=3000)
        main_tid = threading.get_ident()

        panel._preview_patient_cleanup(1, 30, 10, panel)
        assert _process_until(lambda: bool(fake.preview_calls) and bool(shown), timeout_ms=3000)
        assert main_tid not in set(fake.preview_calls)

        shown.clear()
        panel._on_check_consistency_clicked()
        assert _process_until(
            lambda: bool(fake.consistency_calls) and bool(shown), timeout_ms=3000
        )
        assert main_tid not in set(fake.consistency_calls)
    finally:
        panel.deleteLater()
        QCoreApplication.processEvents()


def test_activity_probe_fails_closed_before_destructive_cleanup(qapp, monkeypatch):
    from PacsClient.pacs.workstation_ui.settings_ui import storage_cleanup_panel as scp

    fake = _FakeManager(work_seconds=0.0)
    panel = _build_panel_with_fake_manager(qapp, fake)
    warnings = []
    monkeypatch.setattr(scp.QMessageBox, "warning", lambda *args: warnings.append(args))
    try:
        panel.set_activity_probe(lambda: ["a DICOM import is running"])
        assert panel._can_start_destructive_cleanup(panel) is False
        assert warnings

        panel.set_activity_probe(lambda: [])
        assert panel._can_start_destructive_cleanup(panel) is True

        def _probe_failed():
            raise RuntimeError("synthetic probe failure")

        panel.set_activity_probe(_probe_failed)
        assert panel._can_start_destructive_cleanup(panel) is False
    finally:
        panel.deleteLater()
        QCoreApplication.processEvents()
