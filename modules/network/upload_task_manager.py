# PacsClient/utils/upload_task_manager.py
from __future__ import annotations
import json
import time
import threading
from pathlib import Path
from typing import Callable, Optional, Dict, Any, List
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal, QThread

# از کدهای موجود شما
from PacsClient.utils import get_attachments_uploaded
from PacsClient.utils.config import ATTACHMENT_PATH
from modules.network.upload_download_attchments import upload_attachments_for_study

# ---------- مدل کار ----------
@dataclass
class UploadJob:
    study_uid: str
    retries: int = 0
    max_retries: int = 3
    backoff_sec: float = 2.0
    status: str = field(default="queued")  # queued|running|success|error|canceled
    last_error: Optional[str] = None

# ---------- Worker ----------
class _UploadWorker(QObject):
    finished = Signal(str, dict)     # study_uid, summary
    errored = Signal(str, str)       # study_uid, error
    progress = Signal(str, int, int) # study_uid, current, total

    def __init__(self, job: UploadJob):
        super().__init__()
        self.job = job
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        """اجرای یک job با بک‌آف و retry"""
        job = self.job
        job.status = "running"

        # فایل‌های آپلود‌شده تا این لحظه را از DB/CSV شما می‌خوانیم (مثل کدی که خودت استفاده می‌کنی)
        attachments_uploaded = get_attachments_uploaded(job.study_uid) or ""

        # تلاش با ریتری
        for attempt in range(job.retries, job.max_retries + 1):
            if self._stop:
                job.status = "canceled"
                self.errored.emit(job.study_uid, "Canceled by user")
                return

            try:
                # نکته: متد شما خودش فایل‌های تکراری را فیلتر می‌کند (بر اساس DB/CSV)
                # و خروجی خلاصه می‌دهد.
                summary = upload_attachments_for_study(
                    study_uid=job.study_uid,
                    attachments_uploaded=attachments_uploaded,
                    verbose=False
                )

                # شمارش پیشرفت (دلخواه: اگر بخواهی حین آپلود هر فایل سیگنال بدهی،
                # می‌توانی داخل upload_attachments_for_study هوک/کالبک اضافه کنی)
                self.progress.emit(job.study_uid, summary.get("success", 0), summary.get("total", 0))

                if summary.get("failed", 0) == 0:
                    job.status = "success"
                    self.finished.emit(job.study_uid, summary)
                    return
                else:
                    # اگر برخی فایل‌ها خطا داشتند، همین را موفقیت نسبی در نظر بگیر
                    job.status = "success"
                    self.finished.emit(job.study_uid, summary)
                    return

            except Exception as e:
                job.last_error = str(e)
                if attempt < job.max_retries:
                    # backoff
                    time.sleep(job.backoff_sec * (2 ** attempt))
                    continue
                job.status = "error"
                self.errored.emit(job.study_uid, job.last_error)
                return

# ---------- Manager ----------
class UploadManager(QObject):
    jobQueued   = Signal(str)                 # study_uid
    jobStarted  = Signal(str)                 # study_uid
    jobProgress = Signal(str, int, int)       # study_uid, current, total
    jobDone     = Signal(str, dict)           # study_uid, summary
    jobError    = Signal(str, str)            # study_uid, error
    jobCanceled = Signal(str)                 # study_uid

    _instance_lock = threading.Lock()
    _instance: Optional["UploadManager"] = None

    @classmethod
    def instance(cls) -> "UploadManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = UploadManager()
            return cls._instance

    # ---------- init ----------
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._queue: List[UploadJob] = []
        self._active: Dict[str, Dict[str, Any]] = {}  # study_uid -> {thread, worker, qthread, job}
        self._max_concurrent = 2
        self._persist_path = Path(ATTACHMENT_PATH) / ".upload_queue.json"
        self._load_queue_from_disk()

        # اگر بعد از ری‌استارت صف داشتی، ادامه بده
        self._drain_queue_async()

    # ---------- persistence ----------
    def _load_queue_from_disk(self):
        try:
            if self._persist_path.exists():
                data = json.load(self._persist_path.open("r", encoding="utf-8"))
                self._queue = [UploadJob(**item) for item in data.get("queue", [])]
        except Exception:
            self._queue = []

    def _save_queue_to_disk(self):
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            json.dump(
                {"queue": [job.__dict__ for job in self._queue if job.status in ("queued", "running")]},
                self._persist_path.open("w", encoding="utf-8"),
                ensure_ascii=False, indent=2
            )
        except Exception:
            pass

    # ---------- public API ----------
    def enqueue(self, study_uid: str) -> bool:
        """اگر job مشابه در صف یا در حال اجرا بود، دوباره اضافه نمی‌کنیم."""
        if study_uid in self._active or any(j.study_uid == study_uid and j.status in ("queued", "running") for j in self._queue):
            return False

        job = UploadJob(study_uid=study_uid)
        self._queue.append(job)
        self._save_queue_to_disk()
        self.jobQueued.emit(study_uid)

        self._drain_queue_async()
        return True

    def cancel(self, study_uid: str) -> bool:
        # اگر در حال اجراست
        active = self._active.get(study_uid)
        if active:
            worker: _UploadWorker = active["worker"]
            worker.stop()
            self.jobCanceled.emit(study_uid)
            return True
        # اگر در صف است
        for j in self._queue:
            if j.study_uid == study_uid and j.status == "queued":
                j.status = "canceled"
                self._queue = [k for k in self._queue if k.status not in ("canceled", "success")]
                self._save_queue_to_disk()
                self.jobCanceled.emit(study_uid)
                return True
        return False

    def stats(self) -> Dict[str, Any]:
        return {
            "active": list(self._active.keys()),
            "queued": [j.study_uid for j in self._queue if j.status == "queued"]
        }

    # ---------- internal ----------
    def _drain_queue_async(self):
        # تا سقف هم‌زمانی کار اجرا کن
        while len(self._active) < self._max_concurrent and any(j.status == "queued" for j in self._queue):
            job = next(j for j in self._queue if j.status == "queued")
            self._start_job(job)

    def _start_job(self, job: UploadJob):
        job.status = "running"
        self._save_queue_to_disk()
        self.jobStarted.emit(job.study_uid)

        qthread = QThread()
        worker = _UploadWorker(job)
        worker.moveToThread(qthread)

        # اتصال سیگنال‌ها
        qthread.started.connect(worker.run)
        worker.progress.connect(self.jobProgress.emit)
        worker.finished.connect(self._on_worker_finished)
        worker.errored.connect(self._on_worker_errored)

        # ذخیره مراجع
        self._active[job.study_uid] = {"qthread": qthread, "worker": worker, "job": job}

        # پاکسازی بعد از finish/err
        worker.finished.connect(lambda *_: self._teardown(job.study_uid))
        worker.errored.connect(lambda *_: self._teardown(job.study_uid))

        qthread.start()

    def _teardown(self, study_uid: str):
        ctx = self._active.pop(study_uid, None)
        if not ctx:
            return
        qthread: QThread = ctx["qthread"]
        worker: _UploadWorker = ctx["worker"]

        worker.deleteLater()
        qthread.quit()
        qthread.wait()
        qthread.deleteLater()

        # صف را ذخیره کن و اگر کار مانده، ادامه بده
        self._queue = [j for j in self._queue if not (j.study_uid == study_uid and j.status in ("success", "error", "canceled"))]
        self._save_queue_to_disk()
        self._drain_queue_async()

    def _on_worker_finished(self, study_uid: str, summary: dict):
        self.jobDone.emit(study_uid, summary)

    def _on_worker_errored(self, study_uid: str, error: str):
        self.jobError.emit(study_uid, error)
