"""Observe the existing download queue, then validate media inputs off-thread.

This owns only the dialog continuation. Cancelling it never cancels a transfer
that another viewer or download request may also be using.
"""
import time
from PySide6.QtCore import QObject, QTimer, Signal


class DownloadBeforeMedia(QObject):
    progress = Signal(int, str)
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, manager, study_uids, prepare, parent=None, *, store=None):
        super().__init__(parent)
        if store is None:
            from PacsClient.utils.support_diagnostics import OperationStore
            store = OperationStore()
        self.manager = manager
        self.uids = tuple(dict.fromkeys(study_uids))
        self.prepare = prepare
        self.store = store
        self.operation = None
        self.active = False
        self.started = 0
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.poll)

    def start(self):
        if not self.uids:
            raise ValueError('No study identity selected')
        self.started = time.monotonic()
        self.active = True
        self.timer.start()

    def cancel(self):
        self.active = False
        self.timer.stop()

    def fail(self, message):
        self.cancel()
        self.failed.emit(message)

    def poll(self):
        if not self.active:
            return
        try:
            if time.monotonic() - self.started > 7200:
                self.fail('Download preparation timed out. Review the Download Manager and try again.')
                return
            if self.operation is not None:
                result = self.store.status(self.operation)
                if result['state'] == 'running':
                    return
                if result['state'] != 'succeeded' or result['data']['missing']:
                    self.fail('The selected studies are not fully available. No disc was written. Retry the download.')
                    return
                self.cancel()
                self.ready.emit(result['data'])
                return
            states = [self.manager.state_store.get(uid) for uid in self.uids]
            names = [getattr(getattr(s, 'status', None), 'name', '') for s in states]
            if any(n in ('FAILED', 'CANCELLED') for n in names):
                self.fail('A selected download failed or was cancelled. No disc was written. Review the Download Manager.')
                return
            if any(s is None for s in states) and time.monotonic() - self.started > 180:
                self.fail('Unable to queue all selected studies. Check the server connection and try again.')
                return
            value = int(sum(100 if n == 'COMPLETED' else
                            float(getattr(s, 'progress_percent', 0) or 0)
                            for s, n in zip(states, names)) / len(states))
            self.progress.emit(min(100, max(0, value)),
                               f'Downloading selected studies: {names.count("COMPLETED")} / {len(states)} complete')
            if not self.active:
                return
            if all(n == 'COMPLETED' for n in names):
                self.progress.emit(100, 'Checking downloaded files before preparing the disc...')
                if self.active:
                    self.operation = self.store.start('cd_download_validation', self.prepare)['operation_id']
        except Exception:
            self.fail('Unable to prepare the selected downloads. No disc was written. Please try again.')
