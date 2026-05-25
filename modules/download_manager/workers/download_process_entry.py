"""
Download Process Entry — executed inside a *separate* Python process.

This module intentionally has NO top-level Qt / PySide6 imports so that
the multiprocessing ``spawn`` start-method (Windows default) never tries to
initialise a QApplication in the child process.

All heavy imports are deferred to inside ``_run_download_in_process``.
"""

from __future__ import annotations

# Minimal stdlib that is safe in any process
import multiprocessing as _mp
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.models import DownloadTask


# ─────────────────────────────────────────────────────────────────────────────
# Public subprocess entry point
# ─────────────────────────────────────────────────────────────────────────────

def _run_download_in_process(
    task,                        # DownloadTask — pickled by mp.Process
    config_dict: dict,           # {'socket_host', 'socket_port', 'grpc_host',
                                 #  'grpc_port', 'base_output_dir', 'auth_token'}
    result_queue,                # multiprocessing.Queue  (progress + completion)
    cancel_event,                # multiprocessing.Event  (set → cancel)
    working_dir: str,            # os.getcwd() from parent process
) -> None:
    """Run one full study download in a completely separate Python process.

    The parent QThread polls *result_queue* and re-emits Qt signals.
    Because this function runs in its own interpreter, it has its own GIL —
    the viewer main thread is never starved regardless of how long
    json.loads / base64.b64decode / pydicom hold their respective GILs.

    Messages written to *result_queue* follow this schema:
        {'type': 'progress',   'study_uid': str, 'event_type': str,
         'series_number': str, 'progress_pct': float,
         'downloaded': int,    'total': int}

        {'type': 'completed',  'study_uid': str, 'success': bool,
         'error': str | None}

        {'type': 'error',      'study_uid': str, 'error': str,
         'traceback': str}
    """
    import os
    import asyncio
    import logging
    import time
    from PacsClient.utils.diagnostic_logging import configure_diagnostic_logging, set_log_context

    # ── 1. Working directory (db path is relative to cwd) ────────────────────
    os.chdir(working_dir)

    # ── 2. Logging ──────────────────────────────────────────────────────────
    configure_diagnostic_logging(process_role="download-subprocess", force=True)
    logger = logging.getLogger("download_process_entry")

    t0 = time.monotonic()
    study_uid: str = getattr(task, "study_uid", config_dict.get("study_uid", ""))
    patient_name: str = getattr(task, "patient_name", "?")
    series_count: int = len(getattr(task, "series_list", []))
    set_log_context(
        action_session_id=config_dict.get("action_session_id") or os.getenv("AIPACS_ACTION_SESSION_ID", "-"),
        study_uid=study_uid,
        download_job_id=config_dict.get("download_job_id", "-"),
    )

    # [SPAWN-TIMING] at WARNING so it lands in download_diagnostics.log — its
    # wall-clock timestamp vs the parent's _start_download_worker reveals the
    # process-spawn + entry-import cost (not covered by t0, which starts here).
    logger.warning(
        "▶ [SPAWN-TIMING] Process started | study=%s | patient=%s | series=%d | cwd=%s",
        study_uid[:40], patient_name, series_count, working_dir,
        extra={"component": "ipc", "study_uid": study_uid, "download_job_id": config_dict.get("download_job_id", "-")},
    )
    logger.info(
        "  Config: socket=%s:%s  grpc=%s:%s  out=%s  has_token=%s",
        config_dict.get("socket_host"), config_dict.get("socket_port"),
        config_dict.get("grpc_host"),   config_dict.get("grpc_port"),
        config_dict.get("base_output_dir"), bool(config_dict.get("auth_token")),
    )

    # ── 2b. Lower this subprocess's OS priority (Windows) ────────────────────
    # The download subprocess's response_parse CPU bursts (25-84ms every ~1.8s)
    # compete with the viewer's VTK scroll rendering on shared CPU cores.
    # BELOW_NORMAL_PRIORITY_CLASS lets the OS scheduler favour the viewer thread
    # during scroll while still allowing download to proceed at full I/O speed.
    import sys as _sys
    if _sys.platform == "win32":
        try:
            import ctypes as _ctypes
            _BELOW_NORMAL = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
            _ctypes.windll.kernel32.SetPriorityClass(
                _ctypes.windll.kernel32.GetCurrentProcess(), _BELOW_NORMAL
            )
            logger.info(
                "  Process priority → BELOW_NORMAL_PRIORITY_CLASS (viewer gets CPU headroom)",
                extra={"component": "ipc", "study_uid": study_uid},
            )
        except Exception as _pe:
            logger.debug("  Could not lower process priority: %s", _pe)

    # ── 2c. v2.3.7 R13: Protected-drag dynamic priority throttle. ────────────
    # While the viewer holds a protected stack-drag session, the viewer
    # process touches {user_data}/cache/.drag_active. A daemon thread in
    # this subprocess polls the flag and (when enabled) drops to
    # IDLE_PRIORITY_CLASS while the drag is active; restores to
    # BELOW_NORMAL_PRIORITY_CLASS when the flag goes stale.
    #
    # DISABLED BY DEFAULT (v2.3.7, reverted after log 99). Empirical
    # evidence from log 99 (ui_lag_max 412ms vs log 98's 229ms under
    # comparable load) shows that dropping the subprocess to IDLE while
    # it holds the multiprocessing.Queue IPC mutex causes priority
    # inversion: the viewer (ABOVE_NORMAL) blocks waiting on a lock held
    # by an IDLE-scheduled thread in the subprocess, producing the exact
    # "event_p95 spikes while handler_p95 stays low" pattern observed.
    # BELOW_NORMAL is sufficient separation; keep the infrastructure
    # behind an explicit opt-in in case of future tuning.
    # Opt-in: AIPACS_DRAG_SUBPROC_THROTTLE=1 to enable.
    if _sys.platform == "win32" and os.environ.get("AIPACS_DRAG_SUBPROC_THROTTLE", "0") == "1":
        try:
            import threading as _threading
            import ctypes as _ctypes_poll

            _IDLE_PRIORITY_CLASS = 0x00000040
            _BELOW_NORMAL_PRIORITY_CLASS_POLL = 0x00004000
            _DRAG_STALE_MS = 2000.0   # flag older than this → drag over
            _POLL_INTERVAL = 0.15     # 150ms poll cadence
            _LOG_EXTRA_IPC = {"component": "ipc", "study_uid": study_uid}

            def _resolve_flag_path() -> str:
                try:
                    from aipacs_runtime import user_data_root as _udr
                    return str(_udr() / "cache" / ".drag_active")
                except Exception:
                    return ""

            def _drag_priority_poller() -> None:
                _flag_path = _resolve_flag_path()
                if not _flag_path:
                    return
                _kernel32_p = _ctypes_poll.windll.kernel32
                _hproc = _kernel32_p.GetCurrentProcess()
                _current_class = _BELOW_NORMAL_PRIORITY_CLASS_POLL
                _cancel = cancel_event
                while True:
                    try:
                        if _cancel is not None and _cancel.is_set():
                            try:
                                _kernel32_p.SetPriorityClass(_hproc, _BELOW_NORMAL_PRIORITY_CLASS_POLL)
                            except Exception:
                                pass
                            return
                        _drag_active = False
                        try:
                            _st = os.stat(_flag_path)
                            _age_ms = (time.time() - _st.st_mtime) * 1000.0
                            _drag_active = _age_ms < _DRAG_STALE_MS
                        except FileNotFoundError:
                            _drag_active = False
                        except Exception:
                            _drag_active = False
                        _target = _IDLE_PRIORITY_CLASS if _drag_active else _BELOW_NORMAL_PRIORITY_CLASS_POLL
                        if _target != _current_class:
                            try:
                                _kernel32_p.SetPriorityClass(_hproc, _target)
                                _current_class = _target
                                logger.info(
                                    "[SP] Priority -> %s (drag_active=%s)",
                                    "IDLE" if _target == _IDLE_PRIORITY_CLASS else "BELOW_NORMAL",
                                    _drag_active,
                                    extra=_LOG_EXTRA_IPC,
                                )
                            except Exception as _pe:
                                logger.debug("[SP] SetPriorityClass failed: %s", _pe, extra=_LOG_EXTRA_IPC)
                    except Exception:
                        pass
                    time.sleep(_POLL_INTERVAL)

            _poller_thread = _threading.Thread(
                target=_drag_priority_poller,
                name="aipacs-sp-drag-priority",
                daemon=True,
            )
            _poller_thread.start()
            logger.info(
                "[SP] Drag-priority poller started (opt-in enabled)",
                extra=_LOG_EXTRA_IPC,
            )
        except Exception as _te:
            logger.debug("[SP] Could not start drag-priority poller: %s", _te)

    try:
        # ── 3. Lazy imports (no Qt in the import chain) ───────────────────────
        from pathlib import Path

        # Override DEFAULT_SOCKET_HOST / DEFAULT_SOCKET_PORT *before* any
        # client is constructed so every SocketDicomClient() call picks up
        # the live server the user selected in the UI.
        from modules.download_manager.core import constants as _consts
        _consts.DEFAULT_SOCKET_HOST = config_dict["socket_host"]
        _consts.DEFAULT_SOCKET_PORT = int(config_dict["socket_port"])
        logger.info(
            "  Constants patched: socket_host=%s socket_port=%s",
            _consts.DEFAULT_SOCKET_HOST, _consts.DEFAULT_SOCKET_PORT,
        )

        # Restore auth token in the subprocess's singleton token manager
        auth_token: str | None = config_dict.get("auth_token")
        if auth_token:
            from modules.network.socket_token_manager import get_socket_token_manager
            get_socket_token_manager().set_token(auth_token)
            logger.info("  Auth token restored in subprocess token manager")
        else:
            logger.warning("  ⚠️ No auth token in config_dict — requests may be rejected")

        logger.info("  Importing PacsClient modules...")
        from modules.download_manager.network.grpc_client import GrpcMetadataClient
        from modules.download_manager.storage.database_manager import DatabaseManager
        from modules.download_manager.download.executor import DownloadExecutor
        from modules.download_manager.rules.rule_engine import DownloadRuleEngine
        from modules.download_manager.state.state_store import DownloadStateStore
        logger.warning("  [SPAWN-TIMING] Imports OK (%.3fs)", time.monotonic() - t0)

        # ── 4. Construct independent clients ─────────────────────────────────
        logger.info(
            "  Building gRPC client: %s:%s",
            config_dict["grpc_host"], config_dict["grpc_port"],
        )
        grpc_client = GrpcMetadataClient(
            host=config_dict["grpc_host"],
            port=int(config_dict["grpc_port"]),
        )
        logger.info("  gRPC client ready")

        logger.info("  Building DatabaseManager...")
        database_manager = DatabaseManager()
        logger.warning("  [SPAWN-TIMING] DatabaseManager ready (%.3fs)", time.monotonic() - t0)

        state_store = DownloadStateStore()
        rule_engine = DownloadRuleEngine(state_store, {})
        base_output_dir = Path(config_dict["base_output_dir"])

        executor = DownloadExecutor(
            state_store=state_store,
            rule_engine=rule_engine,
            grpc_client=grpc_client,
            database_manager=database_manager,
            base_output_dir=base_output_dir,
        )

        # Propagate viewed-series hint so SeriesDownloader prioritises it
        _viewed = config_dict.get("viewed_series_number")
        if _viewed:
            executor.viewed_series_number = _viewed
            logger.info("  Viewed series hint: %s", _viewed)

        logger.info(
            "  DownloadExecutor ready (out_dir=%s)", base_output_dir,
        )

        # ── 5. Callbacks ──────────────────────────────────────────────────────
        _progress_count = [0]   # mutable counter visible inside closure

        def _is_cancelled() -> bool:
            return cancel_event.is_set()

        def _progress_cb(
            event_type, series_number, progress_pct, downloaded, total, **_
        ):
            if cancel_event.is_set():
                # Re-use the same DownloadCancelled exception so executor
                # handles cancellation cleanup cleanly.
                from modules.download_manager.workers.download_worker import (
                    DownloadCancelled,
                )
                logger.info(
                    "  Cancellation detected in _progress_cb — raising DownloadCancelled"
                )
                raise DownloadCancelled("Cancelled via process cancel event")
            _progress_count[0] += 1
            if _progress_count[0] == 1 or _progress_count[0] % 10 == 0:
                logger.info(
                    "  Progress #%d  series=%s  %.1f%%  (%d/%d)  event=%s",
                    _progress_count[0], series_number,
                    progress_pct, downloaded, total, event_type,
                )
            try:
                result_queue.put_nowait(
                    {
                        "type": "progress",
                        "study_uid": study_uid,
                        "event_type": str(event_type),
                        "series_number": str(series_number),
                        "progress_pct": float(progress_pct),
                        "downloaded": int(downloaded),
                        "total": int(total),
                    }
                )
            except Exception:
                pass  # Queue full — drop this progress heartbeat

        # ── 6. Run ────────────────────────────────────────────────────────────
        logger.warning(
            "  [SPAWN-TIMING] Starting asyncio event loop (%.3fs since process start)",
            time.monotonic() - t0,
        )
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                executor.execute_download(
                    task=task,
                    progress_callback=_progress_cb,
                    completion_callback=lambda uid, success: None,
                    cancel_check=_is_cancelled,
                )
            )
            elapsed = time.monotonic() - t0
            logger.info(
                "  Download complete: success=%s  elapsed=%.2fs  "
                "downloaded_series=%s  failed_series=%s  total_series=%s  error=%s",
                result.success, elapsed,
                getattr(result, "downloaded_series", "?"),
                getattr(result, "failed_series", "?"),
                getattr(result, "total_series", "?"),
                result.error_message,
            )
            result_queue.put(
                {
                    "type": "completed",
                    "study_uid": study_uid,
                    "success": bool(result.success),
                    "error": result.error_message,
                }
            )
        finally:
            try:
                loop.close()
            except Exception:
                pass
            asyncio.set_event_loop(None)

    except Exception as exc:  # noqa: BLE001
        import traceback

        err_tb = traceback.format_exc()
        elapsed = time.monotonic() - t0
        logger.error(
            "❌ Download process FAILED after %.2fs: %s", elapsed, exc
        )
        logger.error("Traceback:\n%s", err_tb)
        try:
            result_queue.put(
                {
                    "type": "error",
                    "study_uid": study_uid,
                    "error": str(exc),
                    "traceback": err_tb,
                }
            )
        except Exception:
            pass
