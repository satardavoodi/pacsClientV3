"""A user close must not unload modules underneath a queued/native import."""
import ast
from pathlib import Path
from types import SimpleNamespace
import queue
import threading
import time
import pytest

from PySide6 import QtCore, QtWidgets

SOURCE = Path('modules/mpr/advanced_3d_slicer/slicer_modules/AIPacsBackgroundRuntime.py')


def runtime_types(window):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name in {'ViewerCloseGuard', 'Runtime'}]
    exit_codes = []
    namespace = dict(qt=QtCore, queue=queue, time=time, exit_codes=exit_codes,
                     slicer=SimpleNamespace(util=SimpleNamespace(mainWindow=lambda: window),
                                            app=SimpleNamespace(exit=exit_codes.append)))
    exec(compile(ast.Module(body=classes, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace


def test_close_waits_for_load_reply_before_native_teardown():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QMainWindow()
    types = runtime_types(window)
    runtime = types['Runtime'].__new__(types['Runtime'])
    runtime.close_requested = False
    runtime.stopping = False
    runtime.active = False
    runtime.commands = queue.Queue()
    runtime.completed = queue.Queue()
    runtime.lock = threading.Lock()
    runtime.awaiting_reply = {'job'}
    runtime.close_guard = types.get('ViewerCloseGuard', lambda *_: QtCore.QObject())(runtime)
    window.installEventFilter(runtime.close_guard)
    window.show()
    # A queued load is about to execute. Closing must not reach Slicer's unload.
    assert window.close() is False
    assert window.isVisible() and runtime.close_requested
    runtime.poll()
    assert window.isVisible()
    runtime.awaiting_reply.clear()  # Authenticated reply has been sent.
    runtime.poll()
    assert not window.isVisible() and runtime.stopping
    assert types['exit_codes'] == [0]
    window.deleteLater()


def test_cancel_native_close_keeps_session_usable():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    class CancelWindow(QtWidgets.QMainWindow):
        def closeEvent(self, event):
            event.ignore()
    window = CancelWindow()
    types = runtime_types(window)
    runtime = types['Runtime'].__new__(types['Runtime'])
    runtime.close_requested = True
    runtime.stopping = False
    runtime.active = False
    runtime.commands = queue.Queue()
    runtime.completed = queue.Queue()
    runtime.lock = threading.Lock()
    runtime.awaiting_reply = set()
    runtime.close_guard = types.get('ViewerCloseGuard', lambda *_: QtCore.QObject())(runtime)
    window.installEventFilter(runtime.close_guard)
    window.show()
    runtime.poll()
    assert window.isVisible() and not runtime.stopping
    assert not runtime.close_requested
    assert types['exit_codes'] == []
    window.deleteLater()


def test_shutdown_event_pump_cannot_start_a_queued_import():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QMainWindow()
    types = runtime_types(window)
    runtime = types['Runtime'].__new__(types['Runtime'])
    runtime.stopping = True
    runtime.active = False
    runtime.completed = queue.Queue()
    runtime.commands = queue.Queue()
    runtime.commands.put(('job', 'load_dicom', {}))
    calls = []
    runtime.viewer_command = lambda *args: calls.append(args)
    runtime.finish = lambda *args, **kwargs: None
    runtime.poll()
    assert not calls and runtime.commands.qsize() == 1
    window.deleteLater()


def test_worker_does_not_reshow_viewer_when_close_was_requested(monkeypatch):
    from concurrent.futures import Future
    from modules.mpr.advanced_3d_slicer import slicer_launcher, resident_service
    calls, finished = [], []
    future = Future()
    future.set_result({'loaded': True, 'close_requested': True})
    def request(operation, parameters):
        calls.append(operation)
        return future
    service = SimpleNamespace(request=request, wait_until_closed=lambda: 0)
    monkeypatch.setattr(resident_service, 'resident_enabled', lambda: True)
    monkeypatch.setattr(resident_service, 'get_service', lambda: service)
    worker = SimpleNamespace(_remote_payload={'dicom_dir': 'synthetic'},
                             started_signal=SimpleNamespace(emit=lambda: None),
                             finished_signal=SimpleNamespace(emit=finished.append))
    slicer_launcher.SlicerLauncherWorker.run(worker)
    assert calls == ['load_dicom'] and finished == [0]


def test_late_close_rejection_is_completion_not_launch_failure(monkeypatch):
    from concurrent.futures import Future
    from modules.mpr.advanced_3d_slicer import slicer_launcher, resident_service
    finished, errors = [], []
    def request(operation, parameters):
        result = Future()
        if operation == 'load_dicom':
            result.set_result({'loaded': True})
        else:
            result.set_exception(resident_service.ViewerClosing('Advanced Analysis is closing'))
        return result
    service = SimpleNamespace(request=request, wait_until_closed=lambda: 0)
    monkeypatch.setattr(resident_service, 'resident_enabled', lambda: True)
    monkeypatch.setattr(resident_service, 'get_service', lambda: service)
    worker = SimpleNamespace(_remote_payload={'dicom_dir': 'synthetic'},
                             error_signal=SimpleNamespace(emit=errors.append),
                             finished_signal=SimpleNamespace(emit=finished.append))
    slicer_launcher.SlicerLauncherWorker.run(worker)
    assert finished == [0] and errors == []


def test_disconnected_requester_does_not_hold_close_forever():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QMainWindow()
    types = runtime_types(window)
    runtime = types['Runtime'].__new__(types['Runtime'])
    runtime.close_requested = True
    runtime.close_reply_deadline = 0.0
    runtime.stopping = False
    runtime.active = False
    runtime.commands = queue.Queue()
    runtime.completed = queue.Queue()
    runtime.lock = threading.Lock()
    runtime.awaiting_reply = {'disconnected'}
    window.show()
    runtime.poll()
    assert not window.isVisible() and runtime.stopping
    window.deleteLater()


def test_late_show_cannot_restart_a_viewer_the_user_closed():
    from modules.mpr.advanced_3d_slicer.resident_service import ResidentService, ViewerClosing
    starts = []
    class Backend:
        def __init__(self):
            self.closed = False
            starts.append(self)
        def start(self):
            pass
        def alive(self):
            return not self.closed
        def ready(self):
            return True
        def close(self):
            self.closed = True
        def command(self, *args):
            return {'loaded': True}
    service = ResidentService(backend_factory=Backend)
    try:
        service.request('load_dicom').result(2)
        starts[0].closed = True
        with pytest.raises(ViewerClosing):
            service.request('show').result(2)
        assert len(starts) == 1
        service.request('load_dicom').result(2)
        assert len(starts) == 2
    finally:
        service.stop()


def test_resident_disables_implicit_quit_before_creating_window_guard(monkeypatch):
    import os
    monkeypatch.setenv('AIPACS_RESIDENT_ROOT', 'synthetic')
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    node = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                and node.name == 'AIPacsBackgroundRuntime')
    calls = []
    class Base:
        def __init__(self, parent):
            pass
    namespace = dict(os=os, ScriptedLoadableModule=Base,
        WindowGuard=lambda: calls.append('guard'),
        Runtime=lambda guard: SimpleNamespace(initialize=lambda: None),
        slicer=SimpleNamespace(app=SimpleNamespace(
            setQuitOnLastWindowClosed=lambda value: calls.append(('implicit-quit', value)),
            installEventFilter=lambda guard: None, connect=lambda *args: None)))
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    namespace['AIPacsBackgroundRuntime'](SimpleNamespace())
    assert calls == [('implicit-quit', False), 'guard']
