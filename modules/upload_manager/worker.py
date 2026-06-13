"""UploadWorker — a QThread that runs ONE consultation upload via the existing
workflow, with cooperative pause/cancel + live progress (ADR-0009 D3).

It does NOT re-implement transfer logic: ``job.transfer`` performs the real
seal/de-id/quota/upload through the consultation workflow + CloudSyncEngine. The
worker only supplies the cancel/pause checks and marshals progress into the
state store. No subprocess (uploads are I/O-bound HTTP).
"""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QThread, Signal

from .core.enums import UploadStatus
from .state.store import get_state_store

logger = logging.getLogger(__name__)


class UploadWorker(QThread):
    progress = Signal(str)          # job_id (state already updated in store)
    finished_ok = Signal(str)       # job_id
    finished_err = Signal(str, str)  # job_id, message
    paused = Signal(str)            # job_id
    cancelled = Signal(str)         # job_id

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = job
        self._pause_evt = threading.Event()
        self._cancel_evt = threading.Event()

    def request_pause(self) -> None:
        self._pause_evt.set()

    def request_cancel(self) -> None:
        self._cancel_evt.set()

    def run(self) -> None:  # noqa: D401 - best-effort by contract
        from modules.cloud_consultation.sync.engine import (
            UploadCancelled,
            UploadPaused,
        )

        store = get_state_store()
        jid = self.job.job_id
        store.update(jid, status=UploadStatus.UPLOADING, start_time=time.monotonic(),
                     error_message=None)

        def _cancel_check() -> bool:
            return self._cancel_evt.is_set()

        def _pause_check() -> bool:
            return self._pause_evt.is_set()

        def _progress_cb(pr) -> None:
            st = store.get(jid)
            if st is None:
                return
            st.note_progress(
                getattr(pr, "files_done", 0), getattr(pr, "files_total", 0),
                getattr(pr, "bytes_done", 0), getattr(pr, "bytes_total", 0),
                getattr(pr, "current_path", ""),
            )
            store.touch(jid)
            self.progress.emit(jid)

        try:
            remote_id = self.job.transfer(_cancel_check, _pause_check, _progress_cb)
        except UploadPaused:
            store.update(jid, status=UploadStatus.PAUSED)
            self.paused.emit(jid)
            return
        except UploadCancelled:
            store.update(jid, status=UploadStatus.CANCELLED, end_time=time.monotonic())
            self.cancelled.emit(jid)
            return
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            logger.warning("upload job %s failed: %s", jid, exc)
            store.update(jid, status=UploadStatus.FAILED, end_time=time.monotonic(),
                         error_message=str(exc))
            self.finished_err.emit(jid, str(exc))
            return

        store.update(
            jid, status=UploadStatus.COMPLETED, end_time=time.monotonic(),
            remote_folder_id=str(remote_id or ""), percent=100.0,
            dicom_upload_ok=True, metadata_registered=True,
            consultant_assigned=bool(self.job.assigned_consultant),
        )
        self.finished_ok.emit(jid)
