"""Closing and reopening must not race launcher state or replace a live worker."""
from types import SimpleNamespace
import ast
from pathlib import Path
import queue

# Other MPR tests create widgets in this same process; never seed a core-only app.
from PySide6.QtWidgets import QApplication


def test_runtime_error_reports_stage_without_private_exception_text():
    source = Path("modules/mpr/advanced_3d_slicer/slicer_modules/AIPacsBackgroundRuntime.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    runtime = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Runtime")
    method = next(node for node in runtime.body if isinstance(node, ast.FunctionDef) and node.name == "poll")
    namespace = {"queue": queue, "time": SimpleNamespace(sleep=lambda _: None)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    errors = []
    commands = queue.Queue()
    commands.put(("synthetic", "load_dicom", {}))
    state = SimpleNamespace(active=False, completed=queue.Queue(), commands=commands,
                            finish=lambda request, result=None, error=None: errors.append(error))
    def fail(*args):
        state.viewer_stage = "configure views"
        raise RuntimeError("PRIVATE_FIXTURE_DATA")
    state.viewer_command = fail
    namespace["poll"](state)
    assert "configure views" in errors[0]
    assert "RuntimeError" in errors[0]
    assert "PRIVATE_FIXTURE_DATA" not in errors[0]


def test_reopen_during_shutdown_waits_then_opens_selected_series(monkeypatch):
    from modules.mpr.advanced_3d_slicer import slicer_launcher as module
    app = QApplication.instance() or QApplication([])
    launcher = module.SlicerLauncher()
    callbacks, dialogs, launches = [], [], []
    monkeypatch.setattr(module.QTimer, "singleShot", lambda delay, fn: callbacks.append(fn))
    monkeypatch.setattr(module.QMessageBox, "information", lambda *args: dialogs.append(args))
    launcher._is_running = True
    worker = SimpleNamespace(isRunning=lambda: True)
    launcher._worker = worker
    assert launcher.launch_with_dicom("synthetic", series_uid="synthetic-next")
    assert not dialogs and len(callbacks) == 1
    launcher.launch_with_dicom = lambda **params: launches.append(params)
    # Process completion can be delivered before the QThread has returned.
    launcher._is_running = False
    callbacks.pop(0)()
    assert not launches
    worker.isRunning = lambda: False
    callbacks.pop(0)()
    assert launches[0]["series_uid"] == "synthetic-next"
    assert len(launches) == 1 and not dialogs


def test_reopen_timeout_keeps_current_scene_owned(monkeypatch):
    from modules.mpr.advanced_3d_slicer import slicer_launcher as module
    app = QApplication.instance() or QApplication([])
    launcher = module.SlicerLauncher()
    callbacks, dialogs, errors = [], [], []
    monkeypatch.setattr(module.QTimer, "singleShot", lambda delay, fn: callbacks.append(fn))
    monkeypatch.setattr(module.QMessageBox, "information", lambda *args: dialogs.append(args))
    launcher.slicer_error.connect(errors.append)
    launcher._is_running = True
    launcher._worker = SimpleNamespace(isRunning=lambda: True)
    assert launcher.launch_with_dicom("synthetic", series_uid="synthetic-next")
    for _ in range(40):
        if callbacks:
            callbacks.pop(0)()
    assert launcher._is_running
    assert launcher._pending_launch is None
    assert len(dialogs) == 1 and len(errors) == 1 and not callbacks


def test_twenty_closed_sessions_use_fresh_runtime_without_old_scene():
    from modules.mpr.advanced_3d_slicer.resident_service import ResidentService
    backends = []
    class Backend:
        process = None
        connection = {}
        def __init__(self):
            self.closed = False
            self.series = None
            backends.append(self)
        def start(self):
            pass
        def ready(self):
            return True
        def alive(self):
            return not self.closed
        def close(self):
            self.closed = True
        def command(self, operation, parameters, stop, timeout):
            assert self.series is None
            self.series = parameters["series_uid"]
            return self.series
    service = ResidentService(backend_factory=Backend)
    try:
        for index in range(20):
            assert service.request("load_dicom", {"series_uid": str(index)}).result(2) == str(index)
            backends[-1].closed = True
            assert service.wait_until_closed() == 0
        assert len(backends) == 20
    finally:
        service.stop()
