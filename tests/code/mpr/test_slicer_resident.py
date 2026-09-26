"""Resident Slicer must report actual readiness and never block Qt to start."""
from pathlib import Path
import threading
import time
import pytest

from PySide6.QtCore import QCoreApplication


def test_launcher_imports_are_not_runtime_readiness():
    from modules.mpr.advanced_3d_slicer.slicer_launcher import SlicerPrewarmManager
    app = QCoreApplication.instance() or QCoreApplication([])
    manager = SlicerPrewarmManager.instance()
    manager._modules_preloaded = True
    assert manager.is_ready() is False


def test_alive_process_without_readiness_is_a_timeout(monkeypatch):
    from modules.mpr.advanced_3d_slicer import slicer_launcher
    class Process:
        def poll(self):
            return None
    clock = iter([0.0, 2.0])
    monkeypatch.setattr(slicer_launcher.time, "monotonic", lambda: next(clock))
    ready, reason = slicer_launcher.SlicerLauncherWorker._wait_until_launch_ready(
        Process(), None, timeout_s=1)
    assert ready is False
    assert "timeout" in reason


class Backend:
    def __init__(self, gate):
        self.gate = gate
        self.starts = 0
        self.closed = False
        self.connection = {"role": "synthetic"}
        self.thread = None
    def start(self):
        self.starts += 1
        self.thread = threading.get_ident()
    def alive(self):
        return not self.closed
    def ready(self):
        return self.gate.is_set()
    def close(self):
        self.closed = True
    def command(self, operation, parameters, stop, timeout):
        assert self.gate.is_set()
        return {"operation": operation, "parameters": parameters}


def test_warmup_and_user_request_share_one_background_start():
    from modules.mpr.advanced_3d_slicer.resident_service import ResidentService
    gate = threading.Event()
    backend = Backend(gate)
    service = ResidentService(backend_factory=lambda: backend)
    try:
        warm = service.warmup()
        assert service.warmup() is warm
        request = service.request("show")
        assert not request.done()
        gate.set()
        assert request.result(timeout=2)["operation"] == "show"
        assert backend.starts == 1
        assert backend.thread != threading.get_ident()
    finally:
        service.stop()


def test_frozen_warmup_loads_guard_and_presentation_from_installed_runtime(monkeypatch, tmp_path):
    from modules.mpr.advanced_3d_slicer import owned_process, resident_service
    from modules.mpr.advanced_3d_slicer.slicer_custom_app import launch_slicer
    from modules.ai_imaging.eagle_eye_remote import settings
    import aipacs_runtime

    installed = tmp_path / "installed-runtime"
    relative = Path("python/modules/mpr/advanced_3d_slicer")
    guard = installed / relative / "slicer_modules/AIPacsBackgroundRuntime.py"
    startup = installed / relative / "slicer_custom_app/startup_script.py"
    presentation = startup.with_name("presentation.py")
    for path in (guard, startup, presentation):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic installed resource\n", encoding="utf-8")
    executable = installed / "AIPacsAdvancedViewer.exe"
    executable.write_bytes(b"synthetic viewer")
    monkeypatch.setattr(aipacs_runtime, "is_frozen", lambda: True)
    monkeypatch.setattr(aipacs_runtime, "advanced_mpr_runtime_root", lambda: installed)
    monkeypatch.setattr(launch_slicer, "__file__", str(tmp_path / "frozen-core/launch_slicer.py"))
    monkeypatch.setattr(settings, "slicer_environment", lambda: {})
    session = tmp_path / "resident-session"
    def make_session(prefix):
        session.mkdir()
        return str(session)
    monkeypatch.setattr(resident_service.tempfile, "mkdtemp", make_session)
    launched = {}

    class FakeJob:
        def assign(self, process):
            pass
        def close(self):
            pass

    class FakeProcess:
        def wait(self, timeout):
            return 0

    def fake_popen(command, **kwargs):
        launched.update(command=command, environment=kwargs["env"])
        return FakeProcess()

    monkeypatch.setattr(owned_process, "ProcessJob", FakeJob)
    monkeypatch.setattr(resident_service.subprocess, "Popen", fake_popen)
    runtime = resident_service.LocalRuntime("viewer", executable=executable)
    try:
        runtime.start()
        command = launched["command"]
        assert command[command.index("--additional-module-path") + 1] == str(guard.parent)
        assert launched["environment"]["AIPACS_RESIDENT_STARTUP"] == str(startup)
    finally:
        runtime.close()


def test_frozen_warmup_rejects_incomplete_runtime_before_process_creation(monkeypatch, tmp_path):
    from modules.mpr.advanced_3d_slicer import resident_service
    import aipacs_runtime

    executable = tmp_path / "AIPacsAdvancedViewer.exe"
    executable.write_bytes(b"synthetic viewer")
    monkeypatch.setattr(aipacs_runtime, "is_frozen", lambda: True)
    monkeypatch.setattr(aipacs_runtime, "advanced_mpr_runtime_root", lambda: tmp_path)
    launches = []
    monkeypatch.setattr(resident_service.subprocess, "Popen", lambda *args, **kwargs: launches.append(True))
    with pytest.raises(RuntimeError, match="background window guard"):
        resident_service.LocalRuntime("viewer", executable=executable).start()

    base = tmp_path / "python/modules/mpr/advanced_3d_slicer"
    guard = base / "slicer_modules/AIPacsBackgroundRuntime.py"
    guard.parent.mkdir(parents=True)
    guard.write_text("# synthetic guard\n", encoding="utf-8")
    startup = base / "slicer_custom_app/startup_script.py"
    startup.parent.mkdir(parents=True)
    startup.write_text("# synthetic startup\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="presentation is incomplete"):
        resident_service.LocalRuntime("viewer", executable=executable).start()
    assert not launches


def test_stop_during_startup_closes_only_owned_runtime():
    import pytest
    from modules.mpr.advanced_3d_slicer.resident_service import ResidentService
    backend = Backend(threading.Event())
    service = ResidentService(backend_factory=lambda: backend)
    future = service.warmup()
    service.stop()
    with pytest.raises(Exception):
        future.result(timeout=2)
    assert backend.closed or backend.starts == 0


def test_headless_analysis_cannot_use_viewer_scene():
    import numpy as np
    import pytest
    from modules.mpr.advanced_3d_slicer.resident_service import ResidentService
    service = ResidentService("viewer")
    try:
        with pytest.raises(ValueError, match="separate"):
            service.analyze_snapshot(np.zeros((2, 2, 2)), np.eye(4))
    finally:
        service.stop()


def test_cleanup_never_kills_an_unowned_viewer(monkeypatch):
    from types import SimpleNamespace
    from modules.mpr.advanced_3d_slicer import slicer_launcher
    from modules.mpr.advanced_3d_slicer import resident_service
    monkeypatch.setattr(resident_service, "_SHUTTING_DOWN", False)
    monkeypatch.setattr(resident_service, "_SERVICES", {})
    commands = []
    monkeypatch.setattr(slicer_launcher.os.path, "exists", lambda _: False)
    monkeypatch.setattr(slicer_launcher.subprocess, "run",
                        lambda command, **kw: commands.append(command) or SimpleNamespace(returncode=0))
    slicer_launcher.terminate_all_slicer_processes()
    assert not any("/IM" in command for command in commands)


def test_rejected_request_preserves_existing_viewer():
    import pytest
    from modules.mpr.advanced_3d_slicer.resident_service import ResidentService, OperationRejected
    gate = threading.Event()
    gate.set()
    backend = Backend(gate)
    def reject(*args):
        raise OperationRejected("Existing scene is in use")
    backend.command = reject
    service = ResidentService(backend_factory=lambda: backend)
    try:
        with pytest.raises(OperationRejected):
            service.request("load_dicom").result(timeout=2)
        assert not backend.closed
        assert service.state == "ready"
    finally:
        service.stop()


def test_late_start_is_rejected_after_application_shutdown(monkeypatch):
    import pytest
    from modules.mpr.advanced_3d_slicer import resident_service
    monkeypatch.setattr(resident_service, "_SERVICES", {})
    monkeypatch.setattr(resident_service, "_SHUTTING_DOWN", False)
    resident_service.stop_services()
    with pytest.raises(RuntimeError, match="shutting down"):
        resident_service.get_service()


def test_uncertain_viewer_command_preserves_scene_and_prevents_replay():
    from modules.mpr.advanced_3d_slicer.resident_service import ResidentService
    gate = threading.Event()
    gate.set()
    backend = Backend(gate)
    calls = []
    def lost_reply(*args):
        calls.append(args)
        raise ConnectionError("Synthetic lost reply")
    backend.command = lost_reply
    service = ResidentService(backend_factory=lambda: backend)
    try:
        with pytest.raises(ConnectionError):
            service.request("load_dicom").result(timeout=2)
        with pytest.raises(RuntimeError, match="preserved window"):
            service.request("load_dicom").result(timeout=2)
        assert not backend.closed and service.state == "uncertain" and len(calls) == 1
    finally:
        service.stop()


def test_snapshot_rejects_mutable_or_oversize_buffers_before_starting_runtime():
    import numpy as np
    from modules.mpr.advanced_3d_slicer.resident_service import ResidentService
    starts = []
    service = ResidentService("analysis", backend_factory=lambda: starts.append(True))
    try:
        with pytest.raises(ValueError, match="read-only"):
            service.analyze_snapshot(np.zeros((2, 2, 2)), np.eye(4))
        # A zero-stride view represents a huge volume without allocating it.
        huge = np.broadcast_to(np.array(0, dtype=np.uint8), (1024, 1024, 1024))
        with pytest.raises(ValueError, match="dimensions"):
            service.analyze_snapshot(huge, np.eye(4))
        assert not starts
    finally:
        service.stop()


def test_launcher_does_not_report_a_reused_viewer_closed_after_loading(monkeypatch):
    from concurrent.futures import Future
    from types import SimpleNamespace
    from modules.mpr.advanced_3d_slicer import slicer_launcher, resident_service
    started, close = threading.Event(), threading.Event()
    finished = []
    ready = Future()
    ready.set_result({"loaded": True})
    service = SimpleNamespace(request=lambda *args: ready, wait_until_closed=lambda: close.wait(2) and 0)
    monkeypatch.setattr(resident_service, "resident_enabled", lambda: True)
    monkeypatch.setattr(resident_service, "get_service", lambda: service)
    worker = SimpleNamespace(_remote_payload={"dicom_dir": "synthetic"},
                             started_signal=SimpleNamespace(emit=started.set),
                             finished_signal=SimpleNamespace(emit=finished.append))
    thread = threading.Thread(target=lambda: slicer_launcher.SlicerLauncherWorker.run(worker))
    thread.start()
    try:
        assert started.wait(1) and not finished
    finally:
        close.set()
        thread.join(timeout=2)
    assert finished == [0]


@pytest.mark.parametrize("enabled,prewarm,memory,expected", [
    (True, "1", 4 * 1024**3, True), (False, "1", 4 * 1024**3, False),
    (True, "0", 4 * 1024**3, False), (True, "1", 1024**3, False),
])
def test_startup_is_background_and_respects_optional_profile(monkeypatch, enabled, prewarm, memory, expected):
    from concurrent.futures import Future
    from types import SimpleNamespace
    from PySide6.QtCore import QTimer
    import aipacs_runtime
    import psutil
    from PacsClient.utils import advanced_analysis_startup as startup
    from modules.mpr.advanced_3d_slicer import resident_service
    callbacks, quit_callbacks, threads, inspected, warmed = [], [], [], [], []
    original_thread = threading.Thread
    gate = threading.Event()
    def is_enabled(name):
        inspected.append(threading.get_ident())
        gate.wait(2)
        return enabled
    def warmup():
        warmed.append(threading.get_ident())
        future = Future()
        future.set_result({})
        return future
    def make_thread(**kwargs):
        thread = original_thread(**kwargs)
        threads.append(thread)
        return thread
    monkeypatch.setenv("AIPACS_SLICER_RESIDENT", "1")
    monkeypatch.setenv("AIPACS_SLICER_PREWARM", prewarm)
    monkeypatch.setattr(QTimer, "singleShot", lambda delay, callback: callbacks.append(callback))
    monkeypatch.setattr(startup.threading, "Thread", make_thread)
    monkeypatch.setattr(aipacs_runtime, "is_module_enabled", is_enabled)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=memory))
    monkeypatch.setattr(resident_service, "get_service", lambda: SimpleNamespace(warmup=warmup))
    monkeypatch.setattr(resident_service, "stop_services", lambda: None)
    app = SimpleNamespace(aboutToQuit=SimpleNamespace(connect=quit_callbacks.append))
    startup.install(app)
    startup.install(app)
    assert len(callbacks) == 1 and not inspected and not threads
    started = time.monotonic()
    callbacks[0]()
    assert time.monotonic() - started < 0.5  # The profile lookup is still waiting on the worker.
    gate.set()
    threads[0].join(timeout=2)
    assert not threads[0].is_alive()
    assert inspected == [threads[0].ident] and threads[0].ident != threading.get_ident()
    assert bool(warmed) is expected
    quit_callbacks[0]()
