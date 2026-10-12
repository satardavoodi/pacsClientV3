"""Owned worker for bounded license storage and cryptographic operations."""
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, QTimer, Signal
from .signed_license import LicenseError


class LicenseOperation(QObject):
    completed = Signal(str, object)
    failed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='LicenseOperation')
        pool = self.pool
        self.destroyed.connect(lambda: pool.shutdown(wait=False, cancel_futures=True))
        self.future = None
        self.operation = ''
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._poll)

    def start(self, name, function, *args):
        if self.future is not None:
            return False
        self.operation = name
        self.future = self.pool.submit(function, *args)
        self.busy_changed.emit(True)
        self.timer.start()
        return True

    def _poll(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        future, self.future = self.future, None
        operation = self.operation
        try:
            value = future.result()
        except LicenseError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit('The licensing operation could not be completed. Check storage access and retry.')
        else:
            self.completed.emit(operation, value)
        finally:
            # A completion handler may schedule the next operation.
            self.busy_changed.emit(self.future is not None)
