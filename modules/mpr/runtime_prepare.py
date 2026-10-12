"""Prepare Standard MPR Python imports without constructing native views."""
import importlib
import logging
import time
from PySide6.QtCore import QObject, QThread, Slot
from PySide6.QtWidgets import QProgressDialog, QMessageBox

logger = logging.getLogger(__name__)
_workers = set()
_ready = False


def _import_runtime():
    # Imports define classes only. QWidget, VTK/GL and volume construction stay
    # in their existing owners; no viewer instance is created on this thread.
    importlib.import_module('modules.mpr.zeta_mpr.mpr_viewer.widget')


class _ImportWorker(QThread):
    def run(self):
        self.error = None
        started = time.perf_counter()
        try:
            _import_runtime()
        except Exception as error:
            self.error = type(error).__name__
        self.elapsed_ms = (time.perf_counter() - started) * 1000


class MprRuntimePreparation(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.pending = False
        self.dialog = None
        self.worker = None

    def request(self, resume):
        """True means imports are ready; otherwise resume once on the GUI."""
        if _ready:
            return True
        if self.pending:
            return False
        self.pending = True
        self.resume = resume
        self.dialog = QProgressDialog('Preparing MPR components...', None, 0, 0, self.parent())
        self.dialog.setWindowTitle('MPR')
        self.dialog.setCancelButton(None)
        self.dialog.setMinimumDuration(0)
        self.dialog.show()
        self.worker = _ImportWorker()
        worker = self.worker
        _workers.add(worker)
        # Retain a running worker even when its patient owner is destroyed.
        worker.finished.connect(lambda: _workers.discard(worker))
        worker.finished.connect(self._finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        return False

    @Slot()
    def _finished(self):
        global _ready
        worker = self.worker
        self.worker = None
        self.pending = False
        self.dialog.close()
        self.dialog.deleteLater()
        self.dialog = None
        logger.info('[MPR-RUNTIME-PREPARE] elapsed_ms=%.1f outcome=%s',
                    worker.elapsed_ms, worker.error or 'ready')
        resume, self.resume = self.resume, None
        if worker.error:
            QMessageBox.warning(self.parent(), 'MPR', 'Unable to load MPR components. Please retry.')
            return
        _ready = True
        resume()
