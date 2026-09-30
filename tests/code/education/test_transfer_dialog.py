"""Exercise actual transfer worker and dialog retirement with synthetic work."""
import threading

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from modules.education import transfer_dialog as ui


def test_settings_modes_show_only_relevant_actions():
    app = QApplication.instance() or QApplication([])
    for mode in ("export", "import"):
        dialog = ui.EducationTransferDialog(mode=mode)
        dialog.show()
        app.processEvents()
        assert dialog.export_button.isVisible() == (mode == "export")
        assert dialog.import_button.isVisible() == (mode == "import")
        assert dialog.courses.isVisible() == (mode == "export")
        dialog.close()


def _until(predicate):
    for _ in range(300):
        QApplication.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("Worker did not finish")


def test_transfer_runs_off_gui_and_refreshes_only_after_import(monkeypatch):
    app = QApplication.instance() or QApplication([])
    main_thread = threading.get_ident()
    called = []
    def run(path, **kwargs):
        called.append(threading.get_ident())
        kwargs["progress"]("Synthetic progress")
        return dict(courses=2, cases=1, files=4)
    monkeypatch.setattr(ui, "import_package", run)
    dialog = ui.EducationTransferDialog()
    refreshed = []
    dialog.imported.connect(lambda: refreshed.append(True))
    dialog._start("import", "synthetic.aipacs-edu", {})
    assert not dialog.import_button.isEnabled()
    _until(lambda: dialog.worker is None)
    assert called and called[0] != main_thread
    assert refreshed == [True]
    assert "2 courses/resources" in dialog.status.text()
    dialog.close()


def test_close_requests_cancellation_without_destroying_running_worker(monkeypatch):
    app = QApplication.instance() or QApplication([])
    started = threading.Event()
    release = threading.Event()
    def run(path, **kwargs):
        started.set()
        release.wait(3)
        if kwargs["cancel"]():
            raise ui.TransferError("Transfer cancelled.")
        return dict(courses=0, cases=0, files=0)
    monkeypatch.setattr(ui, "export_package", run)
    dialog = ui.EducationTransferDialog()
    dialog.show()
    dialog._start("export", "synthetic.aipacs-edu", {})
    _until(started.is_set)
    dialog.close()
    assert dialog.isVisible() and dialog.worker is not None
    assert dialog.worker.isInterruptionRequested()
    release.set()
    _until(lambda: dialog.worker is None)
    assert dialog.status.text() == "Transfer cancelled."
    dialog.close()
