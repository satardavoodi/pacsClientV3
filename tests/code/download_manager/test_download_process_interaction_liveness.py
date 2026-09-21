"""Download subprocesses must remain runnable independently of viewport lifetime.

Execute the actual process-control functions with a synthetic Windows API. AST
extraction avoids importing VTK, constructing a viewer, registering a real atexit
terminator, or touching clinical files. The prewarm test executes the actual pool
handoff and child entry with in-memory IPC; no native process is suspended.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
WIDGET_ROOT = ROOT / "PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget"


class NativeProcesses:
    def __init__(self):
        self.calls = []
        self.suspend_counts = {101: 0, 202: 0}

    def OpenProcess(self, access, inherit, pid):
        self.calls.append(("open", pid))
        return pid

    def CloseHandle(self, handle):
        self.calls.append(("close", handle))

    def NtSuspendProcess(self, handle):
        self.calls.append(("suspend", handle))
        self.suspend_counts[handle] += 1
        return 0

    def NtResumeProcess(self, handle):
        self.calls.append(("resume", handle))
        self.suspend_counts[handle] = max(0, self.suspend_counts[handle] - 1)
        return 0


def load_controls(filename):
    path = WIDGET_ROOT / filename
    names = {
        "register_download_subprocess", "unregister_download_subprocess",
        "_nt_suspend_download_subprocesses", "_nt_resume_download_subprocesses",
        "terminate_all_download_subprocesses",
    }
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    native = NativeProcesses()
    scope = {
        "sys": SimpleNamespace(platform="win32"),
        "ctypes": SimpleNamespace(windll=SimpleNamespace(kernel32=native, ntdll=native)),
        "_active_download_pids": set(),
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), scope)
    return SimpleNamespace(**scope), native


@pytest.fixture(params=["_vw_globals.py", "_legacy_widget.py"])
def controls(request):
    return load_controls(request.param)


@pytest.mark.parametrize("actions", [
    ("suspend",),  # A viewport never renders / never reaches its settle callback.
    ("suspend", "suspend"),  # Overlapping viewports; one closes without settling.
    ("suspend", "resume", "suspend"),  # Series replacement during the next burst.
    ("resume",),  # Do not release a suspension owned by some other component.
    ("suspend", "resume", "resume"),
])
def test_viewport_interaction_never_controls_download_execution(controls, actions):
    control, native = controls
    control.register_download_subprocess(101)  # Idle spare.
    control.register_download_subprocess(202)  # Active worker / IPC writer.
    for action in actions:
        getattr(control, f"_nt_{action}_download_subprocesses")()
        assert native.suspend_counts == {101: 0, 202: 0}
    assert native.calls == [], "Interaction must not manipulate whole-process execution"
    assert control._active_download_pids == {101, 202}, "Keep shutdown ownership"


def test_prewarm_job_runs_after_unsettled_interaction(controls, monkeypatch, tmp_path):
    from modules.download_manager.workers import prewarm, download_process_entry as entry

    control, native = controls
    monkeypatch.setenv("AIPACS_DM_PREWARM", "1")
    pid = 101
    control.register_download_subprocess(pid)
    control._nt_suspend_download_subprocesses()
    received = []
    messages = []

    class TaskQueue:
        def put(self, item):
            messages.append(item)

        def get(self):
            if native.suspend_counts[pid]:
                raise RuntimeError("Synthetic child cannot execute while suspended")
            return messages.pop(0)

    ready = SimpleNamespace(is_set=lambda: True, set=lambda: None)
    process = SimpleNamespace(pid=pid, is_alive=lambda: True)
    queue = TaskQueue()
    result_queue, cancel = object(), object()
    pool = prewarm.DownloadPrewarmPool()
    pool._spare = {
        "process": process, "task_q": queue, "result_q": result_queue,
        "cancel_evt": cancel, "ready_evt": ready,
    }
    monkeypatch.setattr(pool, "ensure_warm", lambda: None)
    task, config = object(), {"download_job_id": "synthetic-job"}
    adopted = pool.acquire(task, config)
    assert adopted == (process, result_queue, cancel)
    monkeypatch.setattr(entry, "_run_download_in_process", lambda *args: received.append(args))
    # The real entry changes cwd; isolate and restore it via monkeypatch.
    monkeypatch.chdir(tmp_path)
    entry._prewarmed_download_worker_main(queue, result_queue, cancel, str(tmp_path), ready)
    assert received == [(task, config, result_queue, cancel, str(tmp_path))]
    assert pool._spare is None
    assert control._active_download_pids == {pid}


def test_registration_and_retirement_remain_idempotent(controls):
    control, native = controls
    control.register_download_subprocess(101)
    control.register_download_subprocess(101)
    control.register_download_subprocess(202)
    control.unregister_download_subprocess(101)
    control.unregister_download_subprocess(101)
    assert control._active_download_pids == {202}
    assert native.calls == []


@pytest.mark.parametrize("wait_fails", [False, True])
def test_shutdown_still_reaps_registered_downloads(monkeypatch, wait_fails):
    control, native = load_controls("_vw_globals.py")
    calls = []

    class Process:
        def __init__(self, pid):
            self.pid = pid

        def terminate(self):
            calls.append(("terminate", self.pid))

        def wait(self, timeout):
            assert timeout == 2
            if wait_fails:
                raise TimeoutError("Synthetic shutdown wait")

        def kill(self):
            calls.append(("kill", self.pid))

    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=Process))
    for pid in (101, 202):
        control.register_download_subprocess(pid)
    control._nt_suspend_download_subprocesses()
    control.terminate_all_download_subprocesses()
    assert {pid for action, pid in calls if action == "terminate"} == {101, 202}
    assert {pid for action, pid in calls if action == "kill"} == ({101, 202} if wait_fails else set())
    assert control._active_download_pids == set()
    before = list(calls)
    control.terminate_all_download_subprocesses()
    assert calls == before
    assert native.calls == []
