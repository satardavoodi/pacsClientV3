"""Guard: a GUI-thread hang on the patient-close path must leave a trace (A0, 2026-08-23).

WHAT HAPPENED
-------------
2026-08-23 00:47:02, end-user workstation "sanam": Windows recorded
``Application Hang 1002`` for ``AIPacs.exe 3.6.2.0`` (pid 24696), immediately
after a patient-tab close. The app's own logs stop 17 seconds earlier and BOTH
of our stall diagnostics reported nothing, because both are structurally blind:

* **F8** ``[MAIN_THREAD_STALL]`` is a ``QTimer`` on the main thread. It measures
  ``now - last_fire`` when it NEXT fires, so it can only report a stall that
  ENDED. Max recorded stall for that session: 1 188 ms -- for a 17 s hang.
* **F11** ``[MAIN_THREAD_STALL_TRACE]`` is a Python daemon thread. It cannot run
  at all while the main thread holds the GIL inside a long C call --
  ``gc.collect()`` over a 2 378 MB heap of VTK wrappers, a VTK render-window
  destructor, a GPU driver call.

WHAT THIS GUARDS
----------------
1. ``native_fault_log.hang_watchdog`` -- built on
   ``faulthandler.dump_traceback_later``, whose timer runs on a NATIVE thread and
   therefore fires while the GIL is held. ``exit=False``: observation only.
2. The patient-close path emits a breadcrumb BEFORE each step, so a step the
   process dies inside is identifiable by its missing ``done`` line.

Every assertion here fails on the pre-fix codebase (the symbols do not exist).
"""

from __future__ import annotations

import faulthandler
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PacsClient.utils import native_fault_log as nfl  # noqa: E402

_LIFECYCLE = (ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
              / "patient_widget_core" / "_pw_lifecycle.py")
_NFL = ROOT / "PacsClient" / "utils" / "native_fault_log.py"


def _lifecycle_src() -> str:
    return _LIFECYCLE.read_text(encoding="utf-8")


def _def_body(src: str, marker: str) -> str:
    """Source of one definition, bounded at the NEXT top-level ``def``.

    Never a fixed character count: this repo has broken four guard tests that
    way, each time because someone added a docstring and the window silently
    slid off the end of the assertion.
    """
    start = src.index(marker)
    tail = src[start + len(marker):]
    nxt = re.search(r"\n(?:@|def |class )", tail)
    return src[start:start + len(marker) + (nxt.start() if nxt else len(tail))]


@pytest.fixture()
def armed_fault_log(tmp_path, monkeypatch):
    """Enable the native fault log into a tmp dir and restore pytest's afterwards."""
    monkeypatch.delenv("AIPACS_NATIVE_FAULT_LOG", raising=False)
    monkeypatch.delenv("AIPACS_HANG_WATCHDOG", raising=False)
    monkeypatch.delenv("AIPACS_HANG_WATCHDOG_SECONDS", raising=False)
    nfl.reset_for_tests()
    path = nfl.enable_native_fault_log(tmp_path)
    assert path is not None
    try:
        yield Path(path)
    finally:
        handle = nfl._handle
        nfl.reset_for_tests()
        try:
            faulthandler.cancel_dump_traceback_later()
        except Exception:
            pass
        try:
            faulthandler.enable()  # back to stderr BEFORE closing our fd
        except Exception:
            pass
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# The watchdog itself
# ---------------------------------------------------------------------------

def test_watchdog_fires_on_an_overrunning_block(armed_fault_log):
    """A block that overruns must leave a stack dump -- the whole point of A0."""
    log = armed_fault_log
    before = log.read_text(encoding="utf-8", errors="replace")
    assert "Timeout" not in before

    with nfl.hang_watchdog("unit-test-overrun", seconds=0.2) as armed:
        assert armed is True, "watchdog must arm when the fault log is enabled"
        time.sleep(1.2)

    content = log.read_text(encoding="utf-8", errors="replace")
    assert "Timeout" in content, (
        "an overrunning block left no trace -- this is exactly the 2026-08-23 "
        "failure mode the watchdog exists to prevent"
    )
    # It dumped a stack, not just a header.
    assert "File " in content


def test_watchdog_is_silent_when_the_block_completes(armed_fault_log):
    """No dump for a normal close -- routine teardown must not pollute the log."""
    log = armed_fault_log
    with nfl.hang_watchdog("unit-test-fast", seconds=5.0) as armed:
        assert armed is True
    time.sleep(0.3)
    assert "Timeout" not in log.read_text(encoding="utf-8", errors="replace")


def test_watchdog_never_kills_the_process(armed_fault_log):
    """``exit=False``: a fired watchdog observes, it does not abort the app."""
    with nfl.hang_watchdog("unit-test-survives", seconds=0.1):
        time.sleep(0.5)
    assert True  # reaching here at all is the assertion


def test_watchdog_is_not_reentrant(armed_fault_log):
    """faulthandler keeps ONE timer -- a nested arm would cancel the outer one
    and lose the dump we actually care about, so inner uses must no-op."""
    with nfl.hang_watchdog("outer", seconds=5.0) as outer:
        assert outer is True
        with nfl.hang_watchdog("inner", seconds=5.0) as inner:
            assert inner is False
    # Depth unwinds cleanly, so the next arm still works.
    with nfl.hang_watchdog("after", seconds=5.0) as again:
        assert again is True


def test_watchdog_noops_without_a_fault_log_handle(monkeypatch):
    """No open handle means nowhere to dump: skip, never open a second file."""
    monkeypatch.delenv("AIPACS_HANG_WATCHDOG", raising=False)
    nfl.reset_for_tests()
    assert nfl._handle is None
    with nfl.hang_watchdog("no-handle") as armed:
        assert armed is False


def test_watchdog_kill_switch(armed_fault_log, monkeypatch):
    monkeypatch.setenv("AIPACS_HANG_WATCHDOG", "0")
    assert nfl.hang_watchdog_enabled() is False
    with nfl.hang_watchdog("disabled", seconds=0.1) as armed:
        assert armed is False
        time.sleep(0.4)
    assert "Timeout" not in armed_fault_log.read_text(encoding="utf-8", errors="replace")


def test_watchdog_defaults(monkeypatch):
    monkeypatch.delenv("AIPACS_HANG_WATCHDOG", raising=False)
    monkeypatch.delenv("AIPACS_HANG_WATCHDOG_SECONDS", raising=False)
    assert nfl.hang_watchdog_enabled() is True
    assert nfl.hang_watchdog_seconds() == 5.0
    # Garbage and non-positive values fall back rather than disabling the timer.
    monkeypatch.setenv("AIPACS_HANG_WATCHDOG_SECONDS", "not-a-number")
    assert nfl.hang_watchdog_seconds() == 5.0
    monkeypatch.setenv("AIPACS_HANG_WATCHDOG_SECONDS", "0")
    assert nfl.hang_watchdog_seconds() == 5.0
    monkeypatch.setenv("AIPACS_HANG_WATCHDOG_SECONDS", "1.5")
    assert nfl.hang_watchdog_seconds() == 1.5


def test_watchdog_uses_the_gil_independent_api():
    """A Python thread cannot sample a main thread that holds the GIL -- that is
    why F11 missed the hang. The watchdog must use faulthandler's C timer."""
    src = _NFL.read_text(encoding="utf-8")
    body = _def_body(src, "def hang_watchdog(")
    assert "dump_traceback_later" in body
    assert "exit=False" in body
    assert "cancel_dump_traceback_later" in body
    # Not a Python thread pretending to be a watchdog.
    assert "threading" not in body and "Thread(" not in body


# ---------------------------------------------------------------------------
# The close path is wired to it
# ---------------------------------------------------------------------------

def test_close_step_logs_before_the_body_runs():
    """The ``start`` line is the load-bearing half: a step the process dies
    inside is only identifiable by having a start and no done."""
    body = _def_body(_lifecycle_src(), "def _close_step(")
    start_at = body.index("[CLOSE_PATH] %s start")
    arm_at = body.index("with _hang_watchdog(label):")
    # rindex, not index: the FIRST yield is the kill-switch early-return path.
    guarded_yield_at = body.rindex("yield")
    assert start_at < arm_at < guarded_yield_at, (
        "the breadcrumb and the watchdog must both precede the step running"
    )
    assert "finally:" in body and "done ms=" in body


def test_deferred_gc_is_wrapped():
    """gc.collect() is the one unlogged, unbounded, GIL-holding step on the
    close path -- deferring it in 2026-06-27 moved the freeze, not its length."""
    body = _def_body(_lifecycle_src(), "def _run_deferred_close_gc(")
    assert '_close_step("deferred_close_gc")' in body
    assert "gc.collect()" in body


def test_exit_patient_widget_is_wrapped():
    """The synchronous teardown -- viewer cleanup, release_mpr_children, VTK
    widget destruction -- logged nothing at INFO, so a block inside it was
    indistinguishable from the app simply stopping."""
    src = _lifecycle_src()
    body = _def_body(src, "    def exit_patient_widget(")
    assert '_close_step("exit_patient_widget")' in body
    assert "self._exit_patient_widget_impl()" in body
    # The real teardown still exists and is unchanged in substance.
    assert "def _exit_patient_widget_impl(self):" in src
    impl = src[src.index("def _exit_patient_widget_impl(self):"):]
    assert "self.cleanup_all_viewers()" in impl
    assert "release_mpr_children" in impl


def test_close_path_timing_kill_switch_default_on():
    src = _lifecycle_src()
    assert '_os.getenv("AIPACS_CLOSE_PATH_TIMING", "1")' in src
    body = _def_body(src, "def _close_step(")
    assert "if not _CLOSE_PATH_TIMING:" in body, "=0 must restore the silent legacy path"


def test_close_path_never_depends_on_the_watchdog_importing():
    """A patient close must not fail because a diagnostic could not import."""
    src = _lifecycle_src()
    window = src[src.index("from PacsClient.utils.native_fault_log import hang_watchdog"):]
    # Bounded at the next real definition, not at the decorator -- the fallback
    # stub is itself decorated with @_contextlib.contextmanager.
    window = window[:window.index("def _close_step(")]
    assert "except Exception" in window
    assert "yield False" in window, "a missing watchdog must degrade to a no-op, not an ImportError"
