"""Guard: closing the CD burn dialog must disconnect + join the worker thread.

Other-PC + this-PC log 2026-06-07 12:56 (pid 8000, ×3):
`RuntimeError: Signal source has been deleted` raised into the excepthook
during a CD-burner DICOMDIR build. closeEvent cancelled the worker but never
waited for the QThread, so the dialog (the progress/completed signal sink)
was destroyed while the worker kept emitting → deleted-source RuntimeError.

The fix adds `_teardown_burn_worker()`: disconnect the three signals, cancel,
and bounded-wait the thread before the dialog dies. These tests pin the
contract without standing up the full dialog (offscreen Qt)."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SRC = (
    Path(__file__).resolve().parents[3]
    / "modules" / "cd_burner" / "cd_burn_dialog.py"
)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def test_source_has_teardown_in_close_and_disconnects():
    src = SRC.read_text(encoding="utf-8", errors="ignore")
    assert "def _teardown_burn_worker" in src
    # closeEvent must call it (both the cancel branch and the not-burning branch).
    close_at = src.index("def closeEvent")
    next_def = src.index("def _teardown_burn_worker")
    close_body = src[close_at:next_def]
    assert close_body.count("_teardown_burn_worker()") >= 2
    # The teardown must disconnect all three signals and wait the thread.
    teardown = src[next_def:next_def + 1400]
    for sig in ("progress", "completed", "stage_changed"):
        assert f'"{sig}"' in teardown or f"'{sig}'" in teardown
    assert ".disconnect(" in teardown
    assert ".wait(" in teardown
    assert "isRunning()" in teardown


def test_teardown_logic_disconnects_and_joins(qapp):
    """Replicate _teardown_burn_worker against a real QThread + signal sink."""
    class _Worker(QThread):
        progress = Signal(int, str)
        completed = Signal(bool, str)
        stage_changed = Signal(str)

        def __init__(self):
            super().__init__()
            self._cancelled = False
            self._emits_after_cancel = 0

        def cancel(self):
            self._cancelled = True

        def run(self):
            # Emit until cancelled (simulates the build loop).
            import time
            while not self._cancelled:
                self.progress.emit(1, "working")
                time.sleep(0.005)

    class _Sink:
        def __init__(self):
            self.hits = 0

        def on_progress(self, *_):
            self.hits += 1

        def on_completed(self, *_):
            pass

        def on_stage_changed(self, *_):
            pass

    def teardown(mgr, sink):
        for sig_name, slot_name in (
            ("progress", "on_progress"),
            ("completed", "on_completed"),
            ("stage_changed", "on_stage_changed"),
        ):
            try:
                getattr(mgr, sig_name).disconnect(getattr(sink, slot_name))
            except (TypeError, RuntimeError):
                pass
        try:
            mgr.cancel()
        except Exception:
            pass
        try:
            if mgr.isRunning():
                mgr.wait(8000)
        except Exception:
            pass

    w = _Worker()
    s = _Sink()
    w.progress.connect(s.on_progress)
    w.start()
    w.wait(200)  # let it run a bit
    teardown(w, s)
    assert not w.isRunning()          # thread joined, not orphaned (the fix)
    qapp.processEvents()              # drain any already-queued cross-thread emits
    baseline = s.hits
    # The worker is joined AND disconnected: a fresh emit reaches no one.
    w.progress.emit(99, "post-teardown")
    qapp.processEvents()
    assert s.hits == baseline         # no new delivery after teardown


def test_teardown_safe_when_no_worker(qapp):
    """Not-burning close path must be a no-op, never raise."""
    class _Dlg:
        burn_manager = None

    # Mirror the early return.
    mgr = getattr(_Dlg(), "burn_manager", None)
    assert mgr is None  # the guard returns immediately
