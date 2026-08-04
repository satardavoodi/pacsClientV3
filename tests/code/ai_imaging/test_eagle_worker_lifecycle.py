# -*- coding: utf-8 -*-
"""Guard: Eagle Eye MG/DX server worker lifecycle must not crash the process.

Regression class (2026-08-03): `AIChatInteractorStyle._current_worker` was the ONLY
strong reference to the running `MamoWorker`/`BoneAgeWorker` QThread, was never
cleared or `deleteLater()`-d, and had no re-entrancy guard. So:

  * a SECOND Eagle Eye run overwrote `_current_worker = worker` while the first
    thread was still talking to the server → the first thread's refcount hit 0 →
    Python GC finalized a *running* QThread → Qt `abort()` ("QThread: Destroyed
    while thread is still running") → the Python process crashes; and
  * closing the patient/tab mid-request dropped the only ref — same abort.

The fix keeps every started worker in a process-level set until it emits
finished/error, adds a busy re-entrancy guard, and fails fast on a dead host. This
mirrors the proven EchoMind `_ORPHANED_WORKERS` detach-don't-wait idiom.

The lifecycle logic (`_ai_worker_busy`, `_register_ai_worker`) is exercised here
against a FAKE worker, without importing the heavy VTK/AI chain — those methods are
plain-Python and touch no VTK. The wiring in start_mg_process/start_dx_process is
source-pinned (importing the module pulls VTK, so we read the source instead).
"""

import ast
import inspect
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MODULE_PATH = (REPO_ROOT / "modules" / "viewer" / "interactor_styles"
               / "ai_chat_interactorstyle.py")
SRC = MODULE_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Extract the pure lifecycle helpers WITHOUT importing the VTK-heavy module.
# ---------------------------------------------------------------------------

def _load_lifecycle_namespace():
    """Exec just the helper functions + the two methods in an isolated namespace."""
    tree = ast.parse(SRC)
    wanted_funcs = {"_eagle_worker_lifecycle_enabled", "_retire_ai_worker"}
    wanted_methods = {"_ai_worker_busy", "_register_ai_worker"}

    # `_LIVE_AI_WORKERS` is an annotated assignment in the source; seed it directly
    # so the extracted helpers close over the same object the tests inspect.
    ns: dict = {"os": __import__("os"), "_LIVE_AI_WORKERS": set()}

    # module-level helper functions
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
            mod = ast.fix_missing_locations(ast.Module([node], []))
            exec(compile(mod, str(MODULE_PATH), "exec"), ns)

    # the two methods off the class body → bind onto a lightweight holder
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "AIChatInteractorStyle":
            for m in node.body:
                if isinstance(m, ast.FunctionDef) and m.name in wanted_methods:
                    mod = ast.fix_missing_locations(ast.Module([m], []))
                    exec(compile(mod, str(MODULE_PATH), "exec"), ns)
    return ns


NS = _load_lifecycle_namespace()


class _FakeSignal:
    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *a):
        for fn in list(self._slots):
            fn(*a)


class _FakeWorker:
    """Stand-in for a QThread worker: running flag + finished/error signals."""

    def __init__(self):
        self._running = False
        self.finished = _FakeSignal()
        self.error = _FakeSignal()
        self.deleted = False

    def isRunning(self):
        return self._running

    def deleteLater(self):
        self.deleted = True


class _Holder:
    """Minimal object with the two bound lifecycle methods."""

    _ai_worker_busy = NS["_ai_worker_busy"]
    _register_ai_worker = NS["_register_ai_worker"]

    def __init__(self):
        self._current_worker = None


@pytest.fixture(autouse=True)
def _clear_live_set():
    NS["_LIVE_AI_WORKERS"].clear()
    yield
    NS["_LIVE_AI_WORKERS"].clear()


# ---------------------------------------------------------------------------
# 1. Flag
# ---------------------------------------------------------------------------

def test_lifecycle_hardening_is_default_on(monkeypatch):
    monkeypatch.delenv("AIPACS_EAGLE_WORKER_LIFECYCLE", raising=False)
    assert NS["_eagle_worker_lifecycle_enabled"]() is True


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("AIPACS_EAGLE_WORKER_LIFECYCLE", "0")
    assert NS["_eagle_worker_lifecycle_enabled"]() is False


# ---------------------------------------------------------------------------
# 2. A running worker keeps a strong ref (cannot be GC'd) and is the busy sentinel
# ---------------------------------------------------------------------------

def test_registered_running_worker_is_busy_and_strongly_referenced(monkeypatch):
    monkeypatch.delenv("AIPACS_EAGLE_WORKER_LIFECYCLE", raising=False)
    h = _Holder()
    w = _FakeWorker()
    w._running = True

    h._register_ai_worker(w)
    assert h._current_worker is w
    assert w in NS["_LIVE_AI_WORKERS"], "a running worker MUST be strongly referenced"
    assert h._ai_worker_busy() is True


def test_finish_clears_ref_and_frees_worker(monkeypatch):
    monkeypatch.delenv("AIPACS_EAGLE_WORKER_LIFECYCLE", raising=False)
    h = _Holder()
    w = _FakeWorker()
    w._running = True
    h._register_ai_worker(w)

    w._running = False
    w.finished.emit({})          # worker signals completion on the GUI thread

    assert h._current_worker is None
    assert w not in NS["_LIVE_AI_WORKERS"]
    assert w.deleted is True, "worker must be scheduled for deletion after it finishes"
    assert h._ai_worker_busy() is False


def test_error_path_also_cleans_up(monkeypatch):
    monkeypatch.delenv("AIPACS_EAGLE_WORKER_LIFECYCLE", raising=False)
    h = _Holder()
    w = _FakeWorker()
    w._running = True
    h._register_ai_worker(w)

    w.error.emit("boom")
    assert h._current_worker is None
    assert w not in NS["_LIVE_AI_WORKERS"]


def test_busy_survives_a_deleted_cpp_object(monkeypatch):
    """isRunning() on a dead C++ QThread raises RuntimeError → treat as not busy."""
    monkeypatch.delenv("AIPACS_EAGLE_WORKER_LIFECYCLE", raising=False)
    h = _Holder()

    class _Dead(_FakeWorker):
        def isRunning(self):
            raise RuntimeError("Internal C++ object (QThread) already deleted.")

    h._current_worker = _Dead()
    assert h._ai_worker_busy() is False
    assert h._current_worker is None


def test_second_worker_does_not_evict_the_first_from_the_live_set(monkeypatch):
    """The crash: a 2nd run must not drop the ONLY ref to the 1st running worker."""
    monkeypatch.delenv("AIPACS_EAGLE_WORKER_LIFECYCLE", raising=False)
    h = _Holder()
    w1 = _FakeWorker(); w1._running = True
    h._register_ai_worker(w1)
    # (in production the busy-guard blocks a 2nd start; but even if one is forced,
    #  the first worker stays alive in the process-level set)
    w2 = _FakeWorker(); w2._running = True
    h._register_ai_worker(w2)

    assert w1 in NS["_LIVE_AI_WORKERS"], "first (still-running) worker must NOT be GC-eligible"
    assert w2 in NS["_LIVE_AI_WORKERS"]


# ---------------------------------------------------------------------------
# 3. Source pins for the wiring that can't be exec'd without VTK
# ---------------------------------------------------------------------------

def test_start_mg_process_has_reentrancy_guard_and_registers_worker():
    body = SRC.split("def start_mg_process", 1)[1].split("def start_dx_process", 1)[0]
    assert "_ai_worker_busy()" in body, "MG start must refuse a concurrent run"
    assert "_register_ai_worker(worker)" in body, "MG worker must be lifecycle-tracked"
    assert "self._current_worker = worker" not in body, \
        "the raw single-ref assignment must be gone (it is the crash)"


def test_start_dx_process_has_reentrancy_guard_and_registers_worker():
    body = SRC.split("def start_dx_process", 1)[1]
    assert "_ai_worker_busy()" in body
    assert "_register_ai_worker(worker)" in body
    assert "self._current_worker = worker" not in body


def test_requests_use_connect_read_timeout_tuples():
    """A dead host must fail fast, not hang a worker thread for the full budget."""
    assert "timeout=(10, 240)" in SRC   # MG run_full_analysis
    assert "timeout=(10, 360)" in SRC   # DX bone-age predict
    assert "timeout=240)" not in SRC    # the old scalar is gone


def test_mg_overlay_safety_timer_outlasts_the_request_timeout():
    """The overlay must not vanish while the request is still alive (invites a re-click)."""
    assert "safety_timer.start(260000)" in SRC   # 260s > 240s read budget
    assert "safety_timer.start(120000)" not in SRC
