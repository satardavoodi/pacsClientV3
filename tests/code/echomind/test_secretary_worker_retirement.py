from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from modules.EchoMind.viewer_chat.ai_chat_api import ApiWorker
from PacsClient.pacs.workstation_ui.home_ui.secretary_button_widget import SecretaryButtonWidget


def test_finished_transcription_clears_deleted_worker_before_next_request():
    app = QApplication.instance() or QApplication([])
    widget = SecretaryButtonWidget()
    for _ in range(2):
        worker = ApiWorker(lambda: {"ok": True}, parent=widget)
        widget._worker = worker
        widget._workers.append(worker)
        worker.start()
        assert worker.wait(2000)
        widget._retire_worker(worker)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert widget._worker is None
        assert not widget._workers
    widget.cleanup()
    widget.close()


def test_retiring_previous_worker_keeps_new_active_worker():
    app = QApplication.instance() or QApplication([])
    widget = SecretaryButtonWidget()
    previous = ApiWorker(lambda: None, parent=widget)
    current = ApiWorker(lambda: None, parent=widget)
    widget._worker = current
    widget._workers.extend((previous, current))
    widget._retire_worker(previous)
    assert widget._worker is current
    widget._retire_worker(current)
    widget.cleanup()
    widget.close()
