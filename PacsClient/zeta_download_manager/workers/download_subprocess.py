"""
Download Subprocess Entry Point
================================
Top-level function that runs the entire download pipeline inside a *separate OS
process*.  Because each OS process has its OWN Python GIL, the download code's
GIL-heavy operations (base64, gzip, json, pydicom loops) can NEVER block the
main process's viewer VTK render calls.

Design rules
------------
* This module is imported by the **main process** only to get the function
  reference for multiprocessing.Process(target=...).  All heavy imports are
  therefore LAZY (inside the function), so the main process does not pay any
  startup cost.

* The function signature uses only picklable types so that Windows 'spawn'
  mode can serialise it without issues.

* No Qt / PySide6 is imported anywhere in this module.  The subprocess has no
  Qt event loop and does not need one.

* State updates from DownloadExecutor go to an in-process DownloadStateStore
  with no observers registered → they are silent no-ops from the perspective
  of the main process.  The only output channel to the main process is the
  ``progress_queue``.

Progress queue message format
------------------------------
Each dict pushed to ``progress_queue`` has a ``'type'`` key:

    progress  → {'type':'progress',  'study_uid':str, 'event_type':str,
                  'series_number':str, 'progress_percent':float,
                  'downloaded':int, 'total':int}

    completed → {'type':'completed', 'study_uid':str,
                  'success':bool, 'error':str}
"""

import logging

_LOG_FORMAT = "%(asctime)s [DL-PROC] %(levelname)s %(name)s: %(message)s"


# ---------------------------------------------------------------------------
# Subprocess entry function  (MUST be module-level for pickle / spawn)
# ---------------------------------------------------------------------------

def run_download_subprocess(
    task,               # DownloadTask  (picklable frozen dataclass)
    base_output_dir,    # str — base directory for all downloads
    socket_host,        # str — socket server host
    socket_port,        # int — socket server port
    auth_token,         # str — JWT authentication token
    grpc_host,          # str — gRPC server host
    grpc_port,          # int — gRPC server port
    progress_queue,     # multiprocessing.Queue — outbound progress events
    cancel_event,       # multiprocessing.Event — set by main process to cancel
    log_level,          # int  — logging level (logging.DEBUG / INFO …)
):
    """
    Execute the complete DICOM download pipeline in an isolated subprocess.

    This is the ``target`` function for ``multiprocessing.Process``.  It runs
    entirely in its own OS process and therefore owns its own GIL.  Any Python
    code here — no matter how GIL-heavy — cannot affect the main process's
    Qt/VTK render thread.

    Parameters
    ----------
    task : DownloadTask
        Frozen dataclass describing what to download.  Must be picklable
        (it is, because DownloadTask uses only stdlib-picklable types).
    base_output_dir : str
        Absolute path to the root downloads folder.
    socket_host / socket_port : str / int
        Socket server coordinates.
    auth_token : str
        Pre-authenticated JWT.  Injected into the subprocess's token-manager
        singleton so all socket clients pick it up automatically.
    grpc_host / grpc_port : str / int
        gRPC server coordinates.
    progress_queue : multiprocessing.Queue
        Queue to which progress/completion dicts are pushed.
    cancel_event : multiprocessing.Event
        The main process sets this to request cancellation.
    log_level : int
        Python logging level.
    """

    # ── 1. Configure logging for this process ────────────────────────────────
    logging.basicConfig(level=log_level, format=_LOG_FORMAT, force=True)
    logger = logging.getLogger("download_subprocess")
    logger.info(
        f"[SP] Subprocess started | patient={task.patient_name} "
        f"| study={task.study_uid[:30]}..."
    )

    # ── 1b. Lower this process's OS priority so VTK scroll in the viewer
    # process is not starved when the download subprocess does CPU-heavy
    # response_parse or memory-heavy body transfer.
    # BELOW_NORMAL_PRIORITY_CLASS (0x4000) on Windows gives the viewer
    # higher scheduler priority without stalling the download.
    import sys as _sys
    if _sys.platform == "win32":
        try:
            import ctypes as _ctypes
            _BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            _kernel32 = _ctypes.windll.kernel32
            _kernel32.SetPriorityClass(_kernel32.GetCurrentProcess(), _BELOW_NORMAL_PRIORITY_CLASS)
            logger.info("[SP] Process priority set to BELOW_NORMAL (viewer gets priority)")
        except Exception as _e:
            logger.debug(f"[SP] Could not set process priority: {_e}")

    # ── 2. Lazy imports (nothing Qt-related) ─────────────────────────────────
    import asyncio
    from pathlib import Path as _Path

    # Inject the auth token into this process's singleton token-manager FIRST.
    # SeriesDownloader creates SocketDicomClient internally and calls
    # ensure_authenticated() which reads from this singleton.
    from PacsClient.utils.socket_token_manager import get_socket_token_manager
    get_socket_token_manager().set_token(auth_token, user={})
    logger.info("[SP] Auth token set in subprocess token manager")

    # Download stack — all Qt-free at import time
    from PacsClient.zeta_download_manager.state.state_store import DownloadStateStore
    from PacsClient.zeta_download_manager.rules.rule_engine import DownloadRuleEngine
    from PacsClient.zeta_download_manager.network.grpc_client import GrpcMetadataClient
    from PacsClient.zeta_download_manager.storage.database_manager import DatabaseManager
    from PacsClient.zeta_download_manager.download.executor import DownloadExecutor

    # ── 3. Build in-process executor with a SILENT state store (no observers) ─
    state_store = DownloadStateStore()   # no UIObserver registered → silent
    rule_engine = DownloadRuleEngine(state_store, {})
    grpc_client = GrpcMetadataClient(host=grpc_host, port=grpc_port)
    db_manager  = DatabaseManager()

    executor = DownloadExecutor(
        state_store=state_store,
        rule_engine=rule_engine,
        grpc_client=grpc_client,
        database_manager=db_manager,
        base_output_dir=_Path(base_output_dir),
    )

    # ── 4. Progress callback → sends messages to the queue ───────────────────
    def _progress_cb(event_type, series_number, progress_percent, downloaded, total, **_kw):
        msg = {
            'type': 'progress',
            'study_uid': task.study_uid,
            'event_type': str(event_type),
            'series_number': str(series_number) if series_number is not None else '',
            'progress_percent': float(progress_percent),
            'downloaded': int(downloaded),
            'total': int(total),
        }
        try:
            progress_queue.put_nowait(msg)
        except Exception:
            # Queue full → drop progress event (non-fatal; viewer still runs fine)
            pass

    # ── 5. Cancel-check → polls the shared Event ─────────────────────────────
    def _cancel_check():
        return cancel_event.is_set()

    # ── 6. Run the async download ─────────────────────────────────────────────
    success   = False
    error_msg = ""
    loop      = None

    try:
        loop   = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result  = loop.run_until_complete(
            executor.execute_download(
                task=task,
                progress_callback=_progress_cb,
                cancel_check=_cancel_check,
            )
        )

        success   = result.success
        error_msg = result.error_message or ""
        logger.info(f"[SP] Download finished | success={success} | error={error_msg!r}")

    except Exception as exc:
        import traceback as _tb
        logger.error(f"[SP] Unhandled exception: {exc}")
        logger.debug(_tb.format_exc())
        error_msg = str(exc)

    finally:
        try:
            if loop and not loop.is_closed():
                loop.close()
        except Exception:
            pass
        asyncio.set_event_loop(None)

    # ── 7. Send completion sentinel ───────────────────────────────────────────
    completion_msg = {
        'type': 'completed',
        'study_uid': task.study_uid,
        'success': success,
        'error': error_msg,
    }
    try:
        progress_queue.put(completion_msg, timeout=10)
    except Exception as e:
        logger.error(f"[SP] Could not put completion message into queue: {e}")

    logger.info(f"[SP] Subprocess exiting | study={task.study_uid[:30]}...")
