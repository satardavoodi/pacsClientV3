"""QThread wrapper that runs a :class:`CloudSyncEngine` transfer off the UI thread.

Imported on demand by the UI (Phase 6), never by the sync package ``__init__`` — so
the engine/state-machine stay importable (and testable) without PySide6.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class SyncWorker(QThread):
    progress = Signal(object)       # SyncProgress
    succeeded = Signal(object)      # remote_folder_id (upload) or dest Path (download)
    failed = Signal(str)

    def __init__(self, engine, operation: str, kwargs: dict, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._operation = operation   # "upload" | "download"
        self._kwargs = dict(kwargs or {})
        # Bridge engine progress to a Qt signal.
        engine.progress_cb = lambda p: self.progress.emit(p)

    def run(self):  # noqa: D401 - QThread entry point
        try:
            if self._operation == "upload":
                result = self._engine.upload(**self._kwargs)
            elif self._operation == "download":
                result = self._engine.download(**self._kwargs)
            else:
                raise ValueError(f"Unknown sync operation: {self._operation!r}")
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
