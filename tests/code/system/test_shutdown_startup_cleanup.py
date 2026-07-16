"""Startup + shutdown process-cleanup guarantees (review 2026-07-14).

The design contract:

* On STARTUP, if a previous AIPacs instance crashed (its QLocalServer pipe was
  released by the OS, so nothing is listening), the new launch must still sweep and
  force-close any orphaned AIPacs process trees BEFORE acquiring the lock — download
  workers, decode/warmup subprocesses, half-dead spares. In a frozen build every one
  of those re-execs ``AIPacs.exe`` (``multiprocessing.freeze_support`` in main.py),
  so the name match catches them.

* On SHUTDOWN (normal close, not just takeover), the process must GUARANTEE it dies:
  kill in-flight download subprocesses explicitly, then a guarded ``os._exit`` so a
  lingering non-daemon thread (native audio callback, Qt Multimedia backend, stuck
  VTK teardown) cannot keep the whole process + child tree alive in Task Manager.

These are structural guards (they pin the wiring that a live crash test would prove).
Pure — no Qt, no processes spawned.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _src(*parts) -> str:
    return (REPO.joinpath(*parts)).read_text(encoding="utf-8", errors="replace")


# ── STARTUP: crash-recovery sweep runs even when nothing is listening ───────
def test_startup_sweeps_orphans_when_no_instance_is_listening():
    """The crash case: a previous instance died, so no QLocalServer is listening,
    but its background processes may still be alive. The no-listener branch MUST
    still force-close them."""
    src = _src("PacsClient", "utils", "single_instance_lock.py")
    body = src.split("def try_acquire", 1)[1].split("\n    def ", 1)[0]
    # the no-listener + takeover branch calls the sweep
    assert "elif takeover:" in body
    seg = body.split("elif takeover:", 1)[1][:400]
    assert "_force_close_other_instances()" in seg, (
        "a launch that finds NO listener must still sweep orphaned trees (crash case)")


def test_sweep_kills_whole_process_trees_not_just_the_top():
    src = _src("PacsClient", "utils", "single_instance_lock.py")
    body = src.split("def _force_close_other_instances", 1)[1].split("\n    def ", 1)[0]
    assert "children(recursive=True)" in body, "must kill the child tree, not only the parent"
    assert "terminate()" in body and ".kill()" in body, "terminate then hard-kill"


def test_sweep_matches_frozen_exe_and_source_main():
    """The matcher must catch BOTH a frozen AIPacs.exe (and its multiprocessing
    children, which re-exec AIPacs.exe) and a source `python main.py` run."""
    src = _src("PacsClient", "utils", "single_instance_lock.py")
    from PacsClient.utils.single_instance_lock import SingleInstanceLock as L
    m = L._proc_is_aipacs
    # frozen exe + its multiprocessing spawn children (image name = AIPacs.exe)
    assert m("AIPacs.exe", r"C:\Program Files\AIPacs\AIPacs.exe", [], "")
    assert m("AIPacs.exe", r"C:\Program Files\AIPacs\AIPacs.exe",
             ["AIPacs.exe", "--multiprocessing-fork", "parent_pid=1234"], "")
    # source run
    assert m("python.exe", r"E:\ai-pacs\...\.venv\python.exe",
             ["python", r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version\main.py"], "")
    # never an unrelated process
    assert not m("chrome.exe", r"C:\chrome.exe", [], "")
    assert not m("python.exe", r"C:\other\python.exe", ["python", "-m", "pytest"], "")


def test_sweep_never_kills_self_or_ancestors_or_descendants():
    """Pure protection-set logic: self + ancestors + descendants are always spared,
    so the sweep can never kill its own launcher or a child it just started."""
    from PacsClient.utils.single_instance_lock import _protected_pids_from_snapshot
    # 100 -> 200 (self) -> 300 (child) -> 400 (grandchild); 900 is unrelated
    pid2ppid = {200: 100, 300: 200, 400: 300, 900: 1}
    protected = _protected_pids_from_snapshot(pid2ppid, self_pid=200)
    assert {200, 100, 300, 400} <= protected      # self + ancestor + descendants
    assert 900 not in protected                    # unrelated is a valid target


# ── SHUTDOWN: a normal close must leave nothing behind ──────────────────────
def test_normal_shutdown_kills_download_subprocesses_explicitly():
    src = _src("main.py")
    fin = src.split("loop.run_forever()", 1)[1]
    assert "terminate_all_download_subprocesses()" in fin, (
        "the normal-close finally must kill in-flight download workers explicitly — "
        "atexit does NOT run after the hard-exit below")


def test_normal_shutdown_has_a_hard_exit_failsafe():
    src = _src("main.py")
    fin = src.split("loop.run_forever()", 1)[1]
    assert "os._exit(0)" in fin, (
        "a lingering non-daemon thread must not keep the process alive after close")
    assert "AIPACS_NO_HARD_EXIT" in fin, "the failsafe needs an escape hatch"


def test_hard_exit_comes_after_the_cleanup():
    """os._exit skips the rest of teardown, so it MUST run last — after the lock
    release, decode-service stop, subprocess kill and log flush."""
    src = _src("main.py")
    fin = src.split("loop.run_forever()", 1)[1]
    assert fin.index("terminate_all_download_subprocesses()") < fin.index("os._exit(0)")
    assert fin.index("shutdown_diagnostic_logging()") < fin.index("os._exit(0)")
    assert fin.index("instance_lock.release()") < fin.index("os._exit(0)")


def test_takeover_path_also_has_a_hard_exit_failsafe():
    """The old instance receiving SHUTDOWN from a newer launch must also be
    guaranteed to die (it had this already — pin it so it can't regress)."""
    src = _src("PacsClient", "utils", "single_instance_lock.py")
    body = src.split("def _initiate_shutdown", 1)[1].split("\n    def ", 1)[0]
    assert "os._exit(0)" in body
    assert "AIPACS_NO_HARD_EXIT" in body


def test_download_subprocess_kill_is_also_registered_at_exit():
    """Belt-and-suspenders: the same kill runs on any normal interpreter exit that
    bypasses main.py's finally."""
    src = _src("PacsClient", "pacs", "patient_tab", "ui", "patient_ui",
               "vtk_widget", "_vw_globals.py")
    assert "atexit" in src
    assert "register(terminate_all_download_subprocesses)" in src


def test_freeze_support_is_enabled_so_frozen_children_are_named_AIPacs():
    """This is what makes the name-based sweep work in the frozen build: a
    multiprocessing spawn child re-execs sys.executable (= AIPacs.exe), so the sweep
    matches it by name after a crash."""
    src = _src("main.py")
    assert "multiprocessing.freeze_support()" in src
