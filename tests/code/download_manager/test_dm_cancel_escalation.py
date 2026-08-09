"""DM-D1 guard tests: the bridge must not let an unacknowledged cancel hold
the pool slot forever.

Root cause (patient 53346, 2026-08-05): `request_cancel()` only sets a
multiprocessing.Event the CHILD checks. A child stuck 26.8 s in spawn/boot
(dl:11208 worker start 11:30:25.09 → dl:11223 child first log 11:30:51.85)
never saw the pause issued at 11:30:30.8, so the single pool slot stayed held
and the freshly opened CRITICAL study waited out the intent chain's full
90x200 ms (recover at 11:30:49, dl:11222) — an 18.3 s visible stall for a
2.2 s transfer.

Fix under test: `_maybe_escalate_cancel()` — after a grace period
(`AIPACS_DM_CANCEL_ESCALATE_S`, default 8 s, <=0 disables) the bridge
terminates the subprocess itself; the exit is reaped by the existing
dead-process handling and the slot frees through the normal removal path.

Report: docs/reports/DM_53346_DELAY_AND_SERIES_203_REDOWNLOAD_2026-08-05.md
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.download_manager.workers import download_process_worker as dpw

WORKER_SRC = (
    PROJECT_ROOT / "modules" / "download_manager" / "workers" / "download_process_worker.py"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# threshold parsing
# ---------------------------------------------------------------------------

def test_escalation_defaults_to_eight_seconds(monkeypatch):
    monkeypatch.delenv("AIPACS_DM_CANCEL_ESCALATE_S", raising=False)
    assert dpw._cancel_escalate_seconds() == 8.0


def test_escalation_env_override(monkeypatch):
    monkeypatch.setenv("AIPACS_DM_CANCEL_ESCALATE_S", "3.5")
    assert dpw._cancel_escalate_seconds() == 3.5


def test_escalation_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("AIPACS_DM_CANCEL_ESCALATE_S", "not-a-number")
    assert dpw._cancel_escalate_seconds() == 8.0


def test_escalation_zero_means_disabled_by_contract():
    assert 'os.environ.get("AIPACS_DM_CANCEL_ESCALATE_S"' in WORKER_SRC
    assert "_CANCEL_ESCALATE_DEFAULT_S = 8.0" in WORKER_SRC


# ---------------------------------------------------------------------------
# behavioural harness: real _maybe_escalate_cancel on a stub worker
# ---------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, alive=True):
        self.pid = 4242
        self._alive = alive
        self.terminate_calls = 0

    def is_alive(self):
        return self._alive

    def terminate(self):
        self.terminate_calls += 1
        self._alive = False


def _make_worker(*, threshold=8.0, cancelled=True, proc=True, alive=True):
    w = dpw.DownloadProcessWorker.__new__(dpw.DownloadProcessWorker)
    w.task = SimpleNamespace(patient_name="TEST^PATIENT", study_uid="1.2.3.test")
    w._cancel_event = threading.Event()
    if cancelled:
        w._cancel_event.set()
    w._process = _FakeProc(alive=alive) if proc else None
    w._escalate_after_s = threshold
    return w


def _tick(monkeypatch, worker, at_s):
    monkeypatch.setattr(dpw.time, "monotonic", lambda: at_s)
    return worker._maybe_escalate_cancel()


def test_no_cancel_no_escalation(monkeypatch):
    w = _make_worker(cancelled=False)
    assert _tick(monkeypatch, w, 100.0) is False
    assert getattr(w, "_cancel_seen_s", None) is None
    assert w._process.terminate_calls == 0


def test_first_observation_arms_but_does_not_terminate(monkeypatch):
    w = _make_worker()
    assert _tick(monkeypatch, w, 100.0) is False
    assert w._cancel_seen_s == 100.0
    assert w._process.terminate_calls == 0


def test_within_grace_no_terminate(monkeypatch):
    w = _make_worker(threshold=8.0)
    _tick(monkeypatch, w, 100.0)
    assert _tick(monkeypatch, w, 107.9) is False
    assert w._process.terminate_calls == 0


def test_grace_elapsed_terminates_exactly_once(monkeypatch):
    """THE fix: the 53346 zombie would have been terminated 8 s after the
    pause instead of holding the slot for 21+ s."""
    w = _make_worker(threshold=8.0)
    _tick(monkeypatch, w, 100.0)          # arm
    assert _tick(monkeypatch, w, 108.01) is True
    assert w._process.terminate_calls == 1
    assert w._cancel_escalated is True
    # latched: later ticks never terminate again
    w._process._alive = True
    assert _tick(monkeypatch, w, 200.0) is False
    assert w._process.terminate_calls == 1


def test_disabled_threshold_never_escalates(monkeypatch):
    w = _make_worker(threshold=0.0)
    _tick(monkeypatch, w, 100.0)
    assert _tick(monkeypatch, w, 999.0) is False
    assert w._process.terminate_calls == 0


def test_negative_threshold_never_escalates(monkeypatch):
    w = _make_worker(threshold=-1.0)
    assert _tick(monkeypatch, w, 100.0) is False
    assert _tick(monkeypatch, w, 999.0) is False
    assert w._process.terminate_calls == 0


def test_missing_process_is_safe(monkeypatch):
    w = _make_worker(proc=False)
    assert _tick(monkeypatch, w, 100.0) is False
    assert _tick(monkeypatch, w, 999.0) is False


def test_dead_process_not_terminated(monkeypatch):
    w = _make_worker(alive=False)
    assert _tick(monkeypatch, w, 100.0) is False
    assert _tick(monkeypatch, w, 999.0) is False
    assert w._process.terminate_calls == 0


def test_53346_timeline_replay(monkeypatch):
    """Replay the measured sequence with the fix: pause at t=0, child stuck in
    boot. Escalation must fire at ~8 s, not wait 21+ s for the child."""
    w = _make_worker(threshold=8.0)
    fired_at = None
    for t in [0.0, 0.2, 2.0, 5.0, 7.9, 8.1, 12.0, 21.0]:
        if _tick(monkeypatch, w, t):
            fired_at = t
            break
    assert fired_at == 8.1, f"escalation fired at {fired_at}, expected first tick past 8 s"
    assert w._process.terminate_calls == 1


# ---------------------------------------------------------------------------
# wiring pins
# ---------------------------------------------------------------------------

def test_poll_loop_calls_escalation_before_liveness_check():
    i_call = WORKER_SRC.index("self._maybe_escalate_cancel()")
    i_alive = WORKER_SRC.index("if self._process.is_alive():", i_call)
    assert i_call < i_alive, (
        "escalation must run in the queue-timeout branch BEFORE the is_alive "
        "check, so a just-terminated child is reaped on the following ticks"
    )


def test_escalated_exit_emits_completed_without_error_signal():
    i = WORKER_SRC.index('if getattr(self, "_cancel_escalated", False):')
    block = WORKER_SRC[i:i + 900]
    assert "self.completed.emit(study_uid, False)" in block
    head = block.split("self.completed.emit", 1)[0]
    assert "self.error.emit" not in head, (
        "a deliberate escalation exit is a preemption, not a failure — it must "
        "not raise an error toast"
    )


def test_escalation_lives_inside_run_poll_timeout_branch():
    i_run = WORKER_SRC.index("def run(self)")
    i_cleanup = WORKER_SRC.index("def _cleanup", i_run)
    i_call = WORKER_SRC.index("self._maybe_escalate_cancel()")
    assert i_run < i_call < i_cleanup
