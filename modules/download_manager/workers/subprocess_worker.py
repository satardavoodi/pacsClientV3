"""
Subprocess Download Worker
===========================
Drop-in replacement for ``DownloadWorker`` (QThread) that executes the entire
download pipeline inside a **separate OS process** instead of a QThread.

Why this solves Mode B viewer lag
----------------------------------
* ``DownloadWorker`` (QThread) shares the Python GIL with the main Qt thread.
  The download loop's Python work (base64, gzip, json, pydicom) holds the GIL
  for 30–750 ms bursts → VTK render calls in the main thread must wait → the
  viewer scroll becomes choppy (22–100 ms per tick instead of <5 ms).

* ``SubprocessDownloadWorker`` moves ALL of that Python work into a **child OS
  process**.  Each OS process owns its own independent GIL.  The main process
  GIL is never touched by download code → viewer render calls are never blocked
  → Mode B scroll performance equals Mode A.

External interface
------------------
``SubprocessDownloadWorker`` is a ``QThread`` subclass with the **same signals
and public methods** as ``DownloadWorker``.  ``WorkerPool`` and
``DownloadManagerWidget`` require zero changes: they call ``start()``,
``request_cancel()``, ``isRunning()``, ``wait()``, and connect
``progress / completed / error / finished`` signals — all of which work
identically.

Internal architecture
---------------------
::

    Main Process (Qt thread + SubprocessDownloadWorker QThread)
    ┌─────────────────────────────────────────────────────────┐
    │  Qt Main Thread   VTK render, scroll — UNCONTESTED GIL │
    │                                                         │
    │  SubprocessDownloadWorker (QThread)                     │
    │    run():                                               │
    │      ├── spawn multiprocessing.Process(target= …)      │
    │      └── bridge_loop():                                 │
    │            poll progress_queue every 50 ms             │
    │            emit progress / completed / error signals   │
    └────────────────────┬────────────────────────────────────┘
                         │ multiprocessing.Queue (progress dicts)
                         │ multiprocessing.Event  (cancel signal)
                         ▼
    Download Subprocess (own GIL, own CPU scheduling)
    ┌─────────────────────────────────────────────────────────┐
    │  asyncio event loop                                     │
    │    GrpcMetadataClient → metadata fetch                  │
    │    SeriesDownloader   → socket recv, base64, gzip,      │
    │                         file write, pydicom DB insert   │
    │  --all GIL-heavy Python work lives here--               │
    │  --zero impact on main process GIL--                   │
    └─────────────────────────────────────────────────────────┘
"""

import logging
import multiprocessing
import queue as _stdlib_queue
from typing import Optional

from PySide6.QtCore import QThread, Signal

from ..core.models import DownloadTask

logger = logging.getLogger(__name__)


class SubprocessDownloadWorker(QThread):
    """
    Download worker that executes downloads in an isolated subprocess.

    Signals (identical to DownloadWorker)
    --------------------------------------
    progress  : (study_uid, event_type, series_number, progress_pct, downloaded, total)
    completed : (study_uid, success)
    error     : (study_uid, error_message)
    """

    # ── Qt Signals (same names/signatures as DownloadWorker) ───────────────
    progress  = Signal(str, str, str, float, int, int)
    completed = Signal(str, bool)
    error     = Signal(str, str)

    # How often the bridge loop checks the queue (seconds).
    # 50 ms gives a responsive UI without busy-waiting.
    _BRIDGE_POLL_TIMEOUT = 0.05

    def __init__(
        self,
        task: DownloadTask,
        executor,           # accepted for API compat with DownloadWorker; NOT used
        parent=None,
    ):
        """
        Parameters
        ----------
        task : DownloadTask
            The frozen dataclass describing what to download.
        executor : DownloadExecutor
            Kept so call-sites need no changes; the subprocess creates its own.
        parent : QObject, optional
        """
        super().__init__(parent)
        self.setObjectName(f"SubprocessWorker-{str(task.patient_name)[:24]}")

        self.task     = task
        # executor is kept for API compatibility but ignored; the subprocess
        # constructs its own executor with its own state store (no Qt observers).
        self._executor_ref = executor

        # ── IPC primitives ──────────────────────────────────────────────────
        # Use the 'spawn' context explicitly:
        #   • Required on Windows (default there anyway)
        #   • Ensures subprocess starts clean with no parent state
        _mp_ctx = multiprocessing.get_context("spawn")
        self._progress_queue: multiprocessing.Queue = _mp_ctx.Queue(maxsize=2000)
        self._cancel_event:   multiprocessing.Event = _mp_ctx.Event()

        # ── Internal state ──────────────────────────────────────────────────
        self._process: Optional[multiprocessing.Process] = None

        logger.info(
            f"[SubprocessWorker] Created for {task.patient_name} "
            f"({task.study_uid[:30]}...)"
        )

    # ── QThread.run() ───────────────────────────────────────────────────────

    def run(self) -> None:
        """
        QThread entry point.

        1. Collects runtime configuration from the main process (auth token,
           server addresses, paths).
        2. Spawns the download subprocess.
        3. Runs the bridge loop: reads progress_queue → emits Qt signals.
        4. Joins / terminates the subprocess before returning.
        When run() returns QThread emits its built-in ``finished`` signal,
        which WorkerPool uses to remove the worker from the pool.
        """
        import logging as _logging
        from .download_subprocess import run_download_subprocess
        from modules.network.socket_token_manager import get_socket_token_manager
        from modules.download_manager.core.constants import (
            DEFAULT_SOCKET_HOST,
            DEFAULT_SOCKET_PORT,
            DEFAULT_GRPC_PORT,
        )

        # ── Gather config from main-process singletons ──────────────────────
        token_mgr  = get_socket_token_manager()
        auth_token = token_mgr.get_token() or ""
        if not auth_token:
            logger.error("[SubprocessWorker] No auth token — cannot start download")
            self.error.emit(self.task.study_uid, "No authentication token")
            self.completed.emit(self.task.study_uid, False)
            return

        base_output_dir = self._resolve_base_output_dir()
        socket_host     = DEFAULT_SOCKET_HOST
        socket_port     = DEFAULT_SOCKET_PORT
        grpc_host       = DEFAULT_SOCKET_HOST
        grpc_port       = DEFAULT_GRPC_PORT
        log_level       = _logging.getLogger().level or _logging.INFO

        logger.info(
            f"[SubprocessWorker] Spawning subprocess | "
            f"patient={self.task.patient_name} | "
            f"socket={socket_host}:{socket_port} | "
            f"grpc={grpc_host}:{grpc_port}"
        )

        # ── Read viewed-series hint from main-process state_store ──────────
        viewed_series_number = None
        try:
            if self._executor_ref and hasattr(self._executor_ref, 'state_store'):
                _st = self._executor_ref.state_store.get(self.task.study_uid)
                if _st:
                    viewed_series_number = getattr(_st, 'viewed_series_number', None)
        except Exception:
            pass

        # ── Spawn the download subprocess ────────────────────────────────────
        mp_ctx = multiprocessing.get_context("spawn")
        self._process = mp_ctx.Process(
            target=run_download_subprocess,
            args=(
                self.task,
                base_output_dir,
                socket_host,
                socket_port,
                auth_token,
                grpc_host,
                grpc_port,
                self._progress_queue,
                self._cancel_event,
                log_level,
                viewed_series_number,
            ),
            name=f"DLProc-{self.task.study_uid[:12]}",
            daemon=True,   # auto-killed if main process exits
        )
        self._process.start()
        logger.info(f"[SubprocessWorker] Subprocess PID={self._process.pid}")

        # ── Bridge loop ──────────────────────────────────────────────────────
        self._bridge_loop()

        # ── Cleanup ──────────────────────────────────────────────────────────
        if self._process is not None and self._process.is_alive():
            logger.warning(
                "[SubprocessWorker] Subprocess still alive after bridge loop — "
                "terminating"
            )
            self._process.terminate()
            self._process.join(timeout=5)

        logger.info(
            f"[SubprocessWorker] QThread run() finished for "
            f"{self.task.study_uid[:30]}..."
        )
        # QThread.finished is emitted automatically when run() returns

    # ── Bridge loop ─────────────────────────────────────────────────────────

    def _bridge_loop(self) -> None:
        """
        Poll the subprocess progress_queue and relay messages to Qt signals.

        Runs inside the QThread (not the main Qt thread), so signal emissions
        are cross-thread and will be delivered safely to the main thread via
        Qt's event queue.
        """
        logger.info("[SubprocessWorker] Bridge loop started")

        while True:
            # ── Try to get a message from the queue ─────────────────────────
            try:
                msg = self._progress_queue.get(timeout=self._BRIDGE_POLL_TIMEOUT)
            except _stdlib_queue.Empty:
                # No message: check whether subprocess is still alive
                if self._process is not None and not self._process.is_alive():
                    logger.warning(
                        "[SubprocessWorker] Subprocess exited without sending "
                        "completion — emitting forced failure completion"
                    )
                    self._emit_forced_completion()
                    break
                # Subprocess running but no message yet → keep polling
                continue

            # ── Dispatch message ─────────────────────────────────────────────
            msg_type = msg.get("type", "")

            if msg_type == "progress":
                self.progress.emit(
                    msg["study_uid"],
                    msg["event_type"],
                    msg["series_number"],
                    float(msg["progress_percent"]),
                    int(msg["downloaded"]),
                    int(msg["total"]),
                )

            elif msg_type == "completed":
                success = bool(msg.get("success", False))
                err     = str(msg.get("error", ""))
                self.completed.emit(msg["study_uid"], success)
                if not success and err:
                    self.error.emit(msg["study_uid"], err)
                break   # Exit bridge loop — download is done

            else:
                logger.debug(f"[SubprocessWorker] Unknown msg type: {msg_type!r}")

        # Drain any residual messages so the queue can be garbage-collected
        try:
            while True:
                self._progress_queue.get_nowait()
        except Exception:
            pass

        logger.info("[SubprocessWorker] Bridge loop finished")

    def _emit_forced_completion(self) -> None:
        """Called when subprocess exits without sending a completion message."""
        ec  = self._process.exitcode if self._process else -1
        err = f"Download subprocess exited unexpectedly (exitcode={ec})"
        logger.error(f"[SubprocessWorker] {err}")
        self.error.emit(self.task.study_uid, err)
        self.completed.emit(self.task.study_uid, False)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _resolve_base_output_dir(self) -> str:
        """Determine the base downloads directory."""
        if self.task.output_dir is not None:
            return str(self.task.output_dir)
        try:
            from PacsClient.utils.config import SOURCE_PATH
            return str(SOURCE_PATH)
        except Exception:
            import os
            return os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "source"
            )

    # ── Cancellation (same API as DownloadWorker) ───────────────────────────

    def request_cancel(self) -> None:
        """
        Request cancellation of the download subprocess.

        Sets the shared cancel_event.  The subprocess checks this via its
        ``cancel_check`` callback at every batch boundary and every file
        iteration → it stops promptly without an abrupt kill.
        """
        self._cancel_event.set()
        logger.info(
            f"[SubprocessWorker] Cancel requested for {self.task.patient_name}"
        )

    def is_cancelled(self) -> bool:
        """Return True if cancellation has been requested."""
        return self._cancel_event.is_set()

    # ── DownloadWorker API shims (unused but required for duck-typing) ───────

    def _on_progress(self, *args, **kwargs):
        """Not called — subprocess sends progress via Queue."""
        pass

    def _on_completion(self, *args, **kwargs):
        """Not called — subprocess sends completion via Queue."""
        pass

    def _cleanup(self) -> None:
        """Called by WorkerPool after run() returns. Nothing extra needed."""
        pass
