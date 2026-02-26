"""
Download Process Worker
=======================
Drop-in replacement for ``DownloadWorker`` that runs every download in
a **completely separate Python process** (``multiprocessing.Process``).

Why this matters
----------------
CPython's GIL is per-process.  No matter how many QThreads you have, they
all share the same GIL and a long C-extension call in the download thread
(``json.loads``, ``base64.b64decode``, …) blocks every other thread,
including the Qt main thread that drives VTK rendering and scroll events.

With ``DownloadProcessWorker``:
- Downloader → own Python interpreter → own GIL
- Viewer / Qt main thread → completely unaffected by download GIL holds
- This QThread becomes a *lightweight bridge* that only polls a
  ``multiprocessing.Queue`` and emits Qt signals (no heavy Python work).

Interface
---------
Identical to ``DownloadWorker`` (same signals + ``request_cancel()`` +
``is_cancelled()``) so it is a transparent drop-in replacement at every
call site.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import time
import uuid
from typing import Optional, Any

from PySide6.QtCore import QThread, Signal

from ..core.models import DownloadTask
from ..download.executor import DownloadExecutor
from PacsClient.utils.diagnostic_logging import set_log_context

logger = logging.getLogger(__name__)

# How long (seconds) the polling loop waits for each queue item.
# 20 ms is a comfortable balance: progress updates arrive timely,
# CPU cost of polling is negligible (<0.1 % of one core).
_QUEUE_POLL_TIMEOUT_S = 0.02

# Maximum rate at which `progress` signals are emitted to the main thread.
# Without this, a large series (500+ images) floods the Qt event queue:
# each queued signal calls _on_worker_progress on the main thread, which
# adds up to seconds of blockage → `event_queue_delay` grows to 16+ s.
# 10 Hz matches the 100 ms throttle already in _on_worker_progress, so
# no visible update quality is lost.
_PROGRESS_EMIT_MIN_INTERVAL_S = 0.10  # emit at most 10×/s


class DownloadProcessWorker(QThread):
    """
    Qt bridge thread for a ``multiprocessing.Process``-based download.

    Signals (identical to DownloadWorker):
        progress  : (study_uid, event_type, series_number, pct, downloaded, total)
        completed : (study_uid, success)
        error     : (study_uid, error_message)
    """

    progress = Signal(str, str, str, float, int, int)
    completed = Signal(str, bool)
    error = Signal(str, str)

    # ── Construction ─────────────────────────────────────────────────────────

    def __init__(
        self,
        task: DownloadTask,
        executor: DownloadExecutor,
        parent=None,
    ) -> None:
        """
        Args:
            task:     Download task (picklable DownloadTask dataclass).
            executor: Executor instance whose grpc_client / base_output_dir
                      are read to build the subprocess config dict.
            parent:   QObject parent (optional).
        """
        super().__init__(parent)
        self.task = task
        self.executor = executor
        self.download_job_id = f"job-{uuid.uuid4().hex[:12]}"
        self.action_session_id = os.getenv("AIPACS_ACTION_SESSION_ID", "-")

        # IPC primitives — created with the default "spawn" context so they
        # work correctly on Windows and match the subprocess start method.
        ctx = mp.get_context("spawn")
        self._result_queue: Any = ctx.Queue(maxsize=1000)
        self._cancel_event: Any = ctx.Event()
        self._process: Optional[Any] = None

        logger.info(
            "✅ DownloadProcessWorker created for %s",
            task.patient_name,
            extra={
                "component": "download",
                "study_uid": task.study_uid,
                "download_job_id": self.download_job_id,
                "action_session_id": self.action_session_id,
            },
        )

    # ── QThread.run ───────────────────────────────────────────────────────────

    def run(self) -> None:  # noqa: C901
        """
        Bridge thread body.

        1. Builds config + spawns the download process.
        2. Polls the result queue and emits Qt signals.
        3. Ensures the download process is terminated on exit.
        """
        study_uid = self.task.study_uid
        set_log_context(
            action_session_id=self.action_session_id,
            study_uid=study_uid,
            download_job_id=self.download_job_id,
        )
        try:
            config_dict = self._build_config_dict()

            # Import the entry-point here (not at worker-module level) so
            # that the subprocess target is evaluated inside the subprocess.
            from .download_process_entry import _run_download_in_process

            ctx = mp.get_context("spawn")
            self._process = ctx.Process(  # type: ignore[assignment]
                target=_run_download_in_process,
                args=(
                    self.task,
                    config_dict,
                    self._result_queue,
                    self._cancel_event,
                    os.getcwd(),
                ),
                name=f"DL-{study_uid[:20]}",
                daemon=True,   # dies automatically if the main process exits
            )
            self._process.start()
            logger.info(
                "🚀 Download subprocess started (pid=%s) for %s",
                self._process.pid,
                self.task.patient_name,
                extra={
                    "component": "ipc",
                    "study_uid": study_uid,
                    "download_job_id": self.download_job_id,
                    "action_session_id": self.action_session_id,
                },
            )

            # ── Poll loop ──────────────────────────────────────────────────
            terminal_message_received = False
            process_dead_since: Optional[float] = None
            # Rate-limiting state for progress signals.
            _last_progress_emit_s: float = 0.0
            _pending_progress_msg: Optional[dict] = None  # latest unsent value
            _last_series_number: Optional[str] = None
            while True:
                try:
                    msg = self._result_queue.get(timeout=_QUEUE_POLL_TIMEOUT_S)
                except Exception:
                    if self._process is None:
                        break

                    # Timeout — check whether the process is still alive.
                    if self._process.is_alive():
                        process_dead_since = None
                        continue

                    # Grace period for final queue messages after process exit.
                    if process_dead_since is None:
                        process_dead_since = time.monotonic()
                        continue
                    if (time.monotonic() - process_dead_since) < 0.5:
                        continue

                    if not terminal_message_received:
                        exit_code = self._process.exitcode
                        logger.error(
                            "❌ Download process (pid=%s) exited unexpectedly (exitcode=%s)",
                            self._process.pid,
                            exit_code,
                        )
                        self.error.emit(
                            study_uid,
                            f"Download process exited unexpectedly (exitcode={exit_code})",
                        )
                        self.completed.emit(study_uid, False)
                    break
                    continue

                msg_type = msg.get("type")
                process_dead_since = None

                if msg_type == "progress":
                    _raw_series = msg.get("series_number", "")
                    _raw_dl = int(msg.get("downloaded", 0))
                    _raw_tot = int(msg.get("total", 0))
                    _series_changed = (_raw_series != _last_series_number)
                    _series_done = (_raw_tot > 0 and _raw_dl >= _raw_tot)
                    _now_s = time.monotonic()
                    _due = (_now_s - _last_progress_emit_s) >= _PROGRESS_EMIT_MIN_INTERVAL_S
                    if _series_changed or _series_done or _due:
                        # Emit and reset pending buffer.
                        _last_series_number = _raw_series
                        _last_progress_emit_s = _now_s
                        _pending_progress_msg = None
                        self.progress.emit(
                            study_uid,
                            msg.get("event_type", ""),
                            _raw_series,
                            float(msg.get("progress_pct", 0.0)),
                            _raw_dl,
                            _raw_tot,
                        )
                    else:
                        # Suppress this signal; keep latest value for next flush.
                        _pending_progress_msg = msg

                elif msg_type == "completed":
                    # Flush any pending progress before the completed signal
                    # so progress bars reach 100 % before the completion UI fires.
                    if _pending_progress_msg is not None:
                        _pm = _pending_progress_msg
                        _pending_progress_msg = None
                        self.progress.emit(
                            study_uid,
                            _pm.get("event_type", ""),
                            _pm.get("series_number", ""),
                            float(_pm.get("progress_pct", 0.0)),
                            int(_pm.get("downloaded", 0)),
                            int(_pm.get("total", 0)),
                        )
                    success = bool(msg.get("success", False))
                    terminal_message_received = True
                    self.completed.emit(study_uid, success)
                    if not success:
                        self.error.emit(
                            study_uid,
                            msg.get("error") or "Download failed (no error message)",
                        )
                    break

                elif msg_type == "error":
                    err_msg = msg.get("error", "Unknown process error")
                    logger.error("❌ Download process error: %s", err_msg)
                    logger.debug("Traceback:\n%s", msg.get("traceback", ""))
                    terminal_message_received = True
                    self.error.emit(study_uid, err_msg)
                    self.completed.emit(study_uid, False)
                    break

            logger.info(
                "✅ DownloadProcessWorker finished for %s (terminal_message_received=%s)",
                self.task.patient_name,
                terminal_message_received,
            )

        except Exception as exc:
            logger.exception("❌ DownloadProcessWorker bridge error: %s", exc)
            self.error.emit(study_uid, str(exc))
            self.completed.emit(study_uid, False)

        finally:
            self._cleanup()

    # ── Cancellation (same interface as DownloadWorker) ───────────────────────

    def request_cancel(self) -> None:
        """Signal the download subprocess to cancel (non-blocking)."""
        self._cancel_event.set()
        logger.info("⏸️ Cancellation requested for %s", self.task.patient_name)

    def is_cancelled(self) -> bool:
        """Return True if cancellation has been requested."""
        return self._cancel_event.is_set()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_config_dict(self) -> dict:
        """Build the config dict that is passed to the subprocess."""
        from PacsClient.utils.socket_config import get_socket_server_settings
        from PacsClient.utils.socket_token_manager import get_socket_token_manager

        socket_settings = get_socket_server_settings()
        auth_token = get_socket_token_manager().get_token()

        cfg = {
            # Use the live server the user selected (via update_socket_server_settings)
            "socket_host": socket_settings.get("host")
                           or getattr(self.executor.grpc_client, "host", ""),
            "socket_port": int(socket_settings.get("port", 50052)),
            # gRPC server (same host, port 50051 by default)
            "grpc_host": getattr(self.executor.grpc_client, "host", ""),
            "grpc_port": int(getattr(self.executor.grpc_client, "port", 50051)),
            # Output directory
            "base_output_dir": str(self.executor.base_output_dir),
            # Auth token — subprocess singleton starts empty; restore it here
            "auth_token": auth_token,
            # Correlation fields (diagnostic logging only)
            "download_job_id": self.download_job_id,
            "action_session_id": self.action_session_id,
            "study_uid": self.task.study_uid,
        }
        logger.debug(
            "[ProcessWorker] _build_config_dict → %s",
            {k: v for k, v in cfg.items() if k != "auth_token"},
        )
        return cfg

    def _cleanup(self) -> None:
        """Terminate the download subprocess and close the IPC queue."""
        pid = getattr(self._process, "pid", None)
        name = self.task.patient_name
        logger.info("[ProcessWorker] 🧹 Cleanup start: patient=%s pid=%s", name, pid)
        try:
            if self._process is not None:
                if self._process.is_alive():
                    logger.info(
                        "[ProcessWorker] 🛑 Terminating running subprocess pid=%s", pid
                    )
                    self._process.terminate()
                    self._process.join(timeout=3.0)
                    if self._process.is_alive():
                        logger.warning(
                            "[ProcessWorker] ⚠️ Subprocess pid=%s did not exit "
                            "after terminate — sending kill", pid
                        )
                        self._process.kill()
                else:
                    logger.debug(
                        "[ProcessWorker] Subprocess pid=%s already exited "
                        "(exitcode=%s)", pid, self._process.exitcode
                    )
        except Exception as exc:
            logger.warning("[ProcessWorker] Process cleanup warning: %s", exc)

        try:
            self._result_queue.close()
            self._result_queue.join_thread()
        except Exception as exc:
            logger.debug("[ProcessWorker] Queue cleanup warning: %s", exc)

        logger.info("[ProcessWorker] 🧹 Cleanup done: patient=%s", name)
