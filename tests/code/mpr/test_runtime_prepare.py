"""First-use imports yield to Qt and never resume a destroyed owner."""
import threading
import time
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QCoreApplication, QEvent


def test_runtime_prepare_is_offthread_and_coalesces(monkeypatch):
    from modules.mpr import runtime_prepare as module
    app = QApplication.instance() or QApplication([])
    release = threading.Event()
    entered = threading.Event()
    thread_ids = []
    def load():
        thread_ids.append(threading.get_ident())
        entered.set()
        assert release.wait(3)
    monkeypatch.setattr(module, '_ready', False)
    monkeypatch.setattr(module, '_import_runtime', load)
    host = QWidget()
    preparation = module.MprRuntimePreparation(host)
    resumed = []
    try:
        assert preparation.request(lambda: resumed.append(1)) is False
        assert entered.wait(2)
        assert preparation.request(lambda: resumed.append(2)) is False
        app.processEvents()  # GUI remains available while import is blocked.
        assert resumed == []
        assert thread_ids != [threading.get_ident()]
    finally:
        release.set()
    deadline = time.monotonic() + 3
    while preparation.pending and time.monotonic() < deadline:
        app.processEvents()
    assert resumed == [1]
    assert preparation.request(lambda: resumed.append(3)) is True
    assert resumed == [1]
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_owner_destruction_during_import_never_resumes(monkeypatch):
    from modules.mpr import runtime_prepare as module
    app = QApplication.instance() or QApplication([])
    release = threading.Event()
    entered = threading.Event()
    def load():
        entered.set()
        assert release.wait(3)
    monkeypatch.setattr(module, '_ready', False)
    monkeypatch.setattr(module, '_import_runtime', load)
    host = QWidget()
    preparation = module.MprRuntimePreparation(host)
    resumed = []
    preparation.request(lambda: resumed.append(1))
    try:
        assert entered.wait(2)
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    finally:
        release.set()
    deadline = time.monotonic() + 3
    while module._workers and time.monotonic() < deadline:
        app.processEvents()
    app.processEvents()
    assert not module._workers
    assert resumed == []
