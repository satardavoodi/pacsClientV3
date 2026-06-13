"""UploadManager — process-wide queue + scheduler + controls (ADR-0009 D3).

Mirrors the Download Manager's queue semantics: ONE active upload at a time, the
rest QUEUED; Pause / Resume / Cancel / Retry / Remove-completed. Reuses the
existing consultation workflow via each job's ``transfer`` callable + the
``UploadWorker`` QThread. Completion fires a Consultation notification.

Stability (ADR-0009 hardening):
  * All mutations happen on the GUI thread (enqueue from the dialog, control
    methods from the UI, scheduler advanced by worker signals which Qt delivers
    to the GUI thread) — so no per-call locking is needed; the singleton
    creation is still locked.
  * ``shutdown()`` (wired to ``QApplication.aboutToQuit``) cooperatively cancels
    the active upload and joins the worker with a bounded wait, so closing the
    app never leaks a thread or crashes mid-upload.
  * Every control + scheduler step is guarded and idempotent; unknown/removed
    job ids are safe no-ops.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from PySide6.QtCore import QObject

from .core.enums import UploadStatus
from .core.models import UploadJob, UploadJobState
from .state.store import get_state_store
from .worker import UploadWorker

logger = logging.getLogger(__name__)

MAX_CONCURRENT_UPLOADS = 1   # mirror Download Manager's single-active contract
_SHUTDOWN_WAIT_MS = 8000     # bounded join per worker on app exit


class UploadManager(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._store = get_state_store()
        self._queue: List[str] = []          # job_ids waiting
        self._jobs: Dict[str, UploadJob] = {}
        self._workers: Dict[str, UploadWorker] = {}
        self._active: Optional[str] = None
        self._shutting_down = False

    # ── public API ─────────────────────────────────────────────────────────────
    def enqueue(self, job: UploadJob) -> str:
        if self._shutting_down:
            return job.job_id
        st = UploadJobState(
            job_id=job.job_id, priority=job.priority, status=UploadStatus.QUEUED,
            consultation_id=job.consultation_id, patient_name=job.patient_name,
            patient_id=job.patient_id, study_date=job.study_date, modality=job.modality,
            assigned_consultant=job.assigned_consultant, target_folder=job.target_folder,
            is_external=job.is_external,
        )
        self._jobs[job.job_id] = job
        self._store.create(st)
        if job.job_id not in self._queue:
            self._queue.append(job.job_id)
        self._pump()
        return job.job_id

    def pause(self, job_id: str) -> None:
        w = self._workers.get(job_id)
        if w is not None and w.isRunning():
            w.request_pause()
        elif job_id in self._queue:
            self._queue.remove(job_id)
            self._store.update(job_id, status=UploadStatus.PAUSED)

    def resume(self, job_id: str) -> None:
        st = self._store.get(job_id)
        if st is None or st.status != UploadStatus.PAUSED:
            return
        if job_id not in self._queue:
            self._store.update(job_id, status=UploadStatus.QUEUED)
            self._queue.append(job_id)
        self._pump()

    def cancel(self, job_id: str) -> None:
        w = self._workers.get(job_id)
        if w is not None and w.isRunning():
            w.request_cancel()
            return
        if job_id in self._queue:
            self._queue.remove(job_id)
        if self._store.get(job_id) is not None:
            self._store.update(job_id, status=UploadStatus.CANCELLED)

    def retry(self, job_id: str) -> None:
        st = self._store.get(job_id)
        if st is None or st.status not in (UploadStatus.FAILED, UploadStatus.CANCELLED):
            return
        if job_id not in self._jobs:
            return  # cannot retry a job whose definition was removed
        self._store.update(job_id, status=UploadStatus.QUEUED, error_message=None,
                           retry_count=(st.retry_count + 1))
        if job_id not in self._queue:
            self._queue.append(job_id)
        self._pump()

    def remove_completed(self) -> None:
        for st in self._store.all():
            if st.status in (UploadStatus.COMPLETED, UploadStatus.CANCELLED, UploadStatus.FAILED):
                if st.job_id == self._active:
                    continue
                self._store.remove(st.job_id)
                self._jobs.pop(st.job_id, None)
                if st.job_id in self._queue:
                    self._queue.remove(st.job_id)

    def remove(self, job_id: str) -> None:
        if self._active == job_id:
            return  # cancel an active job first
        if job_id in self._queue:
            self._queue.remove(job_id)
        self._store.remove(job_id)
        self._jobs.pop(job_id, None)

    def shutdown(self) -> None:
        """Cooperatively cancel the active upload and join the worker (bounded).
        Wired to QApplication.aboutToQuit so app exit never leaks a thread."""
        self._shutting_down = True
        self._queue.clear()
        for jid, w in list(self._workers.items()):
            try:
                if w.isRunning():
                    w.request_cancel()
                    w.wait(_SHUTDOWN_WAIT_MS)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("upload worker shutdown wait skipped (%s): %s", jid, exc)

    # ── scheduler ──────────────────────────────────────────────────────────────
    def _pump(self) -> None:
        if self._shutting_down or self._active is not None or not self._queue:
            return
        # highest priority first, then FIFO
        self._queue.sort(key=lambda j: -int(self._jobs[j].priority) if j in self._jobs else 0)
        job_id = self._queue.pop(0)
        job = self._jobs.get(job_id)
        st = self._store.get(job_id)
        if job is None or st is None:
            # definition/state gone (removed) — skip and try the next one
            self._pump()
            return
        worker = UploadWorker(job)
        worker.finished_ok.connect(self._on_done)
        worker.finished_err.connect(self._on_err)
        worker.paused.connect(self._on_paused)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(worker.deleteLater)
        self._workers[job_id] = worker
        self._active = job_id
        worker.start()

    def _clear_active(self, job_id: str) -> None:
        if self._active == job_id:
            self._active = None
        self._workers.pop(job_id, None)
        self._pump()

    def _on_done(self, job_id: str) -> None:
        self._notify_complete(job_id)
        self._clear_active(job_id)

    def _on_err(self, job_id: str, msg: str) -> None:
        self._clear_active(job_id)

    def _on_paused(self, job_id: str) -> None:
        self._clear_active(job_id)

    def _on_cancelled(self, job_id: str) -> None:
        self._clear_active(job_id)

    def _notify_complete(self, job_id: str) -> None:
        st = self._store.get(job_id)
        if st is None:
            return
        try:
            from modules.cloud_consultation.notifications import inbox
            from modules.cloud_consultation.notifications.models import NotificationKind
            inbox.notify(
                NotificationKind.UPLOAD_DONE,
                title="Consultation Upload Complete",
                body=f"Patient: {st.patient_name or st.patient_id or '-'}  "
                     f"Consultant: {st.assigned_consultant or '-'}",
                consultation_id=st.consultation_id,
            )
        except Exception as exc:  # never break completion on a notification error
            logger.debug("upload completion notification skipped: %s", exc)


_MANAGER: Optional[UploadManager] = None
_MANAGER_LOCK = threading.Lock()


def get_upload_manager() -> UploadManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = UploadManager()
            # Bound the workers to the app lifecycle (cooperative cancel + join).
            try:
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance()
                if app is not None:
                    app.aboutToQuit.connect(_MANAGER.shutdown)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("upload manager shutdown hook not installed: %s", exc)
        return _MANAGER
