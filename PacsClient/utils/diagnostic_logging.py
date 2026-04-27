from __future__ import annotations

import atexit
import contextvars
import logging
import queue
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
import os
import platform
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


_LOG_CONTEXT: contextvars.ContextVar[Dict[str, str]] = contextvars.ContextVar("aipacs_log_context", default={})
_COMPONENT_LEVELS: Dict[str, int] = {}
_COMPONENT_LEVEL_LOCK = threading.Lock()

# Async logging state — file I/O runs on a background thread so `logger.info()`
# on the Qt main thread is a non-blocking queue.put(). See game-changer #1
# (eliminates 50-150ms of synchronous disk I/O per drag cycle).
_ASYNC_LOG_QUEUE: Optional["queue.Queue[logging.LogRecord]"] = None
_ASYNC_LOG_LISTENER: Optional[QueueListener] = None
_ASYNC_LOG_LOCK = threading.Lock()

_DEFAULT_COMPONENT_THRESHOLDS = {
    "viewer": logging.INFO,
    "download": logging.WARNING,
    "zetaboost": logging.INFO,
    "db": logging.INFO,
    "ipc": logging.INFO,
    "ui": logging.INFO,
    "other": logging.INFO,
}

_RESOURCE_MONITOR_STARTED = False
_RESOURCE_MONITOR_LOCK = threading.Lock()


def new_correlation_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def set_log_context(**fields: Optional[str]) -> None:
    current = dict(_LOG_CONTEXT.get())
    for key, value in fields.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = str(value)
    _LOG_CONTEXT.set(current)


def now_ms() -> float:
    return time.perf_counter() * 1000.0


def get_log_context() -> Dict[str, str]:
    return dict(_LOG_CONTEXT.get())


def _format_timing_fields(fields: Dict[str, object]) -> str:
    parts: List[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        safe_key = str(key).replace(" ", "_")
        safe_value = str(value).replace("\\", "/").replace(" ", "_").replace("|", "_")
        parts.append(f"{safe_key}={safe_value}")
    return " ".join(parts)


def log_stage_timing(
    logger_: logging.Logger,
    *,
    component: str,
    function: str,
    stage: str,
    start_ms: float,
    result: str = "ok",
    level: int = logging.INFO,
    min_ms: float = 0.0,
    **fields,
) -> float:
    elapsed_ms = max(0.0, now_ms() - start_ms)
    if elapsed_ms < min_ms:
        return elapsed_ms
    extra = {"component": component, "function": function, "stage": stage, "result": result}
    extra.update({k: v for k, v in fields.items() if v is not None})
    suffix = _format_timing_fields(fields)
    if suffix:
        logger_.log(level, "stage-timing duration_ms=%.2f %s", elapsed_ms, suffix, extra=extra)
    else:
        logger_.log(level, "stage-timing duration_ms=%.2f", elapsed_ms, extra=extra)
    return elapsed_ms


def clear_log_context(*keys: str) -> None:
    if not keys:
        _LOG_CONTEXT.set({})
        return
    current = dict(_LOG_CONTEXT.get())
    for key in keys:
        current.pop(key, None)
    _LOG_CONTEXT.set(current)


@contextmanager
def log_context(**fields: Optional[str]):
    token = _LOG_CONTEXT.set({**_LOG_CONTEXT.get(), **{k: str(v) for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


class HighResolutionFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created)
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


class ContextEnricherFilter(logging.Filter):
    def __init__(self, process_role: str = "main"):
        super().__init__()
        self.process_role = process_role

    def filter(self, record: logging.LogRecord) -> bool:
        context = _LOG_CONTEXT.get()
        record.component = getattr(record, "component", _infer_component(record.name))
        record.process_role = getattr(record, "process_role", self.process_role)
        record.action_session_id = getattr(record, "action_session_id", context.get("action_session_id", "-"))
        record.study_uid = getattr(record, "study_uid", context.get("study_uid", "-"))
        record.series_uid = getattr(record, "series_uid", context.get("series_uid", "-"))
        record.download_job_id = getattr(record, "download_job_id", context.get("download_job_id", "-"))
        record.viewer_event_id = getattr(record, "viewer_event_id", context.get("viewer_event_id", "-"))
        record.function = getattr(record, "function", "-")
        record.stage = getattr(record, "stage", "-")
        record.result = getattr(record, "result", "-")
        return True


class ComponentThresholdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        component = getattr(record, "component", _infer_component(record.name))
        threshold = get_component_level(component)
        return record.levelno >= threshold


class ViewerOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        component = getattr(record, "component", _infer_component(record.name))
        return component == "viewer"


class DownloadOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        component = getattr(record, "component", _infer_component(record.name))
        return component == "download"


class DbOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        component = getattr(record, "component", _infer_component(record.name))
        return component == "db"


class SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler variant that degrades gracefully on Windows locks.

    On Windows, rollover can fail with WinError 32 when another process still
    has the file open. The default handler prints a traceback for every failed
    emit, which adds noise and overhead exactly when diagnostics are needed.

    This handler temporarily skips rollover when the rename is blocked,
    continues appending to the current file, and retries rollover later.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rollover_retry_after_ms: float = 0.0
        self._rollover_retry_ms: float = float(
            os.getenv("AIPACS_LOG_ROLLOVER_RETRY_MS", "5000") or "5000"
        )
        self._rollover_warn_interval_ms: float = float(
            os.getenv("AIPACS_LOG_ROLLOVER_WARN_INTERVAL_MS", "30000") or "30000"
        )
        self._last_rollover_warn_ms: float = 0.0
        self._rollover_failure_count: int = 0

    @staticmethod
    def _is_rollover_lock_error(exc: BaseException) -> bool:
        if isinstance(exc, PermissionError):
            return True
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 32:
            return True
        return False

    def _emit_without_rollover(self, record: logging.LogRecord) -> None:
        if self.stream is None:
            self.stream = self._open()
        logging.FileHandler.emit(self, record)

    def _handle_blocked_rollover(self, exc: BaseException) -> None:
        now = now_ms()
        self._rollover_failure_count += 1
        self._rollover_retry_after_ms = now + max(250.0, self._rollover_retry_ms)
        try:
            if self.stream is None:
                self.stream = self._open()
        except Exception:
            pass

        if (now - self._last_rollover_warn_ms) < self._rollover_warn_interval_ms:
            return

        self._last_rollover_warn_ms = now
        try:
            msg = (
                "[AIPACS][logging] Rollover skipped for locked file "
                f"{self.baseFilename!s}; retrying in {int(self._rollover_retry_ms)}ms.\n"
            )
            sys.stderr.write(msg)
        except Exception:
            pass

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.shouldRollover(record):
                now = now_ms()
                if now >= self._rollover_retry_after_ms:
                    try:
                        self.doRollover()
                        self._rollover_retry_after_ms = 0.0
                    except Exception as exc:
                        if self._is_rollover_lock_error(exc):
                            self._handle_blocked_rollover(exc)
                        else:
                            raise
            self._emit_without_rollover(record)
        except Exception:
            self.handleError(record)


def _infer_component(logger_name: str) -> str:
    name = (logger_name or "").lower()
    if "zeta_download_manager" in name or "download" in name or "socket_client" in name:
        return "download"
    if "database" in name or "db_" in name or "dbmanager" in name:
        return "db"
    if "zeta_boost" in name:
        return "zetaboost"
    if "thumbnail_manager" in name or "thumbnail" in name:
        return "viewer"
    if "viewer" in name or "vtk" in name or "patient_widget_viewer_controller" in name:
        return "viewer"
    if "process" in name or "ipc" in name or "worker" in name:
        return "ipc"
    if "home_ui" in name or "qasync" in name or "mainwindow" in name:
        return "ui"
    return "other"


def _parse_level(level_name: str, fallback: int) -> int:
    if not level_name:
        return fallback
    value = getattr(logging, level_name.upper(), None)
    if isinstance(value, int):
        return value
    return fallback


def _load_component_levels() -> Dict[str, int]:
    levels = dict(_DEFAULT_COMPONENT_THRESHOLDS)
    for component in levels:
        env_key = f"AIPACS_LOG_LEVEL_{component.upper()}"
        levels[component] = _parse_level(os.getenv(env_key, ""), levels[component])
    root_env = os.getenv("AIPACS_LOG_LEVEL", "")
    root_level = _parse_level(root_env, logging.INFO)
    for component, value in levels.items():
        levels[component] = max(value, root_level) if component == "download" else value
    return levels


def set_component_level(component: str, level: int) -> None:
    with _COMPONENT_LEVEL_LOCK:
        _COMPONENT_LEVELS[component] = level


def get_component_level(component: str) -> int:
    with _COMPONENT_LEVEL_LOCK:
        return _COMPONENT_LEVELS.get(component, _DEFAULT_COMPONENT_THRESHOLDS.get(component, logging.INFO))


def _build_formatter() -> logging.Formatter:
    return HighResolutionFormatter(
        fmt=(
            "%(asctime)s | %(levelname)-8s | pid=%(process)d tid=%(thread)d | "
            "component=%(component)s role=%(process_role)s | %(name)s.%(funcName)s | "
            "action=%(action_session_id)s study=%(study_uid)s series=%(series_uid)s "
            "job=%(download_job_id)s viewevt=%(viewer_event_id)s "
            "fn=%(function)s stage=%(stage)s result=%(result)s | %(message)s"
        )
    )


def _ensure_logs_dir() -> Path:
    try:
        from PacsClient.utils.data_paths import LOGS_DIR
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        return LOGS_DIR
    except Exception:
        pass

    base_path: Path
    try:
        from PacsClient.utils.config import BASE_PATH as _BASE_PATH
        base_path = Path(_BASE_PATH)
    except Exception:
        base_path = Path.cwd()

    logs_dir = base_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _install_async_file_logging(
    root: logging.Logger,
    file_handlers: List[logging.Handler],
) -> None:
    """Route ``file_handlers`` behind a single QueueListener.

    The foreground (Qt main thread + worker threads) only enqueues LogRecords;
    actual formatting, filtering, file I/O, and rotation all happen on the
    dedicated listener thread. This removes synchronous disk I/O from the
    hot path.

    Safe to call multiple times (e.g. when ``force=True`` re-configures
    logging): the previous listener is flushed and stopped before a new one
    is started.
    """
    global _ASYNC_LOG_QUEUE, _ASYNC_LOG_LISTENER

    with _ASYNC_LOG_LOCK:
        # Tear down any previous listener before installing a new one.
        prev_listener = _ASYNC_LOG_LISTENER
        _ASYNC_LOG_LISTENER = None
        _ASYNC_LOG_QUEUE = None
    if prev_listener is not None:
        try:
            prev_listener.stop()
        except Exception:
            pass

    # Unbounded queue: we never want to drop diagnostic records. If the
    # listener falls behind, memory pressure shows up on the listener side,
    # not as dropped logs on the producer side.
    log_queue: "queue.Queue[logging.LogRecord]" = queue.Queue(-1)

    # QueueListener owns the real file handlers. respect_handler_level=True
    # so per-handler levels (DEBUG on both) still gate emission.
    listener = QueueListener(log_queue, *file_handlers, respect_handler_level=True)
    listener.daemon = True  # type: ignore[attr-defined]
    listener.start()

    queue_handler = QueueHandler(log_queue)
    queue_handler.setLevel(logging.DEBUG)
    # No formatter/filters on the QueueHandler itself: filters are attached
    # to the real file handlers and run on the listener thread. Attaching
    # them here would pay their cost on the main thread and defeat the
    # purpose of the queue.
    root.addHandler(queue_handler)

    with _ASYNC_LOG_LOCK:
        _ASYNC_LOG_QUEUE = log_queue
        _ASYNC_LOG_LISTENER = listener


def shutdown_diagnostic_logging(timeout_s: float = 2.0) -> None:
    """Flush and stop the async log listener (if any).

    Safe to call from atexit or from main.py's shutdown path. Idempotent.
    ``timeout_s`` is a soft hint; QueueListener.stop() drains the queue
    before returning.
    """
    global _ASYNC_LOG_QUEUE, _ASYNC_LOG_LISTENER
    with _ASYNC_LOG_LOCK:
        listener = _ASYNC_LOG_LISTENER
        _ASYNC_LOG_LISTENER = None
        _ASYNC_LOG_QUEUE = None
    if listener is None:
        return
    try:
        listener.stop()
    except Exception:
        pass


# Best-effort atexit hook so logs are flushed even when shutdown paths in
# main.py are bypassed (crashes, os._exit, etc.). Registered once at import.
atexit.register(shutdown_diagnostic_logging)


def configure_diagnostic_logging(process_role: str = "main", force: bool = True) -> str:
    with _COMPONENT_LEVEL_LOCK:
        _COMPONENT_LEVELS.clear()
        _COMPONENT_LEVELS.update(_load_component_levels())

    root = logging.getLogger()
    if force:
        for handler in list(root.handlers):
            root.removeHandler(handler)

    root_level = _parse_level(os.getenv("AIPACS_LOG_LEVEL", "INFO"), logging.INFO)
    root.setLevel(root_level)

    formatter = _build_formatter()
    context_filter = ContextEnricherFilter(process_role=process_role)
    threshold_filter = ComponentThresholdFilter()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(context_filter)
    console_handler.addFilter(threshold_filter)
    root.addHandler(console_handler)

    logs_dir = _ensure_logs_dir()

    max_bytes = int(os.getenv("AIPACS_LOG_MAX_BYTES", str(20 * 1024 * 1024)) or str(20 * 1024 * 1024))
    backup_count = int(os.getenv("AIPACS_LOG_BACKUP_COUNT", "3") or "3")

    # ---- Async file logging (game-changer #1) ----------------------------
    # File I/O is the single largest source of Qt main-thread stalls during
    # drag/scroll (50-150ms per cycle from 50+ synchronous logger.info calls).
    # We route all file handlers behind a QueueHandler: the call site only
    # does a lock-free queue.put_nowait(); actual disk writes + rotation
    # happen on a dedicated background listener thread. Filters/formatters
    # run on the listener thread too, so the main thread only pays the cost
    # of building the LogRecord (~5-15us).
    #
    # Escape hatch: AIPACS_LOG_SYNC=1 reverts to synchronous file handlers.
    async_enabled = os.getenv("AIPACS_LOG_SYNC", "0").strip().lower() not in ("1", "true", "yes")

    viewer_handler = SafeRotatingFileHandler(
        logs_dir / "viewer_diagnostics.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    viewer_handler.setLevel(logging.DEBUG)
    viewer_handler.setFormatter(formatter)
    viewer_handler.addFilter(context_filter)
    viewer_handler.addFilter(ViewerOnlyFilter())

    download_handler = SafeRotatingFileHandler(
        logs_dir / "download_diagnostics.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    download_handler.setLevel(logging.DEBUG)
    download_handler.setFormatter(formatter)
    download_handler.addFilter(context_filter)
    download_handler.addFilter(DownloadOnlyFilter())
    download_handler.addFilter(threshold_filter)

    db_handler = SafeRotatingFileHandler(
        logs_dir / "db_diagnostics.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    db_handler.setLevel(logging.DEBUG)
    db_handler.setFormatter(formatter)
    db_handler.addFilter(context_filter)
    db_handler.addFilter(DbOnlyFilter())
    db_handler.addFilter(threshold_filter)

    if async_enabled:
        _install_async_file_logging(root, [viewer_handler, download_handler, db_handler])
    else:
        root.addHandler(viewer_handler)
        root.addHandler(download_handler)
        root.addHandler(db_handler)

    app_session_id = os.getenv("AIPACS_ACTION_SESSION_ID") or new_correlation_id("sess")
    os.environ["AIPACS_ACTION_SESSION_ID"] = app_session_id
    set_log_context(action_session_id=app_session_id)

    logging.getLogger(__name__).info(
        "Logging configured: role=%s component_levels=%s logs_dir=%s",
        process_role,
        {k: logging.getLevelName(v) for k, v in _COMPONENT_LEVELS.items()},
        str(logs_dir),
        extra={"component": "ui"},
    )
    start_resource_monitor(process_role=process_role)
    return app_session_id


def start_resource_monitor(process_role: str = "main") -> None:
    global _RESOURCE_MONITOR_STARTED
    with _RESOURCE_MONITOR_LOCK:
        if _RESOURCE_MONITOR_STARTED:
            return
        _RESOURCE_MONITOR_STARTED = True

    try:
        import psutil  # type: ignore
    except Exception:
        logging.getLogger(__name__).debug("resource monitor disabled: psutil unavailable")
        return

    logger = logging.getLogger("aipacs.resource")
    interval_s = float(os.getenv("AIPACS_RESOURCE_MONITOR_INTERVAL_SEC", "2.0") or "2.0")
    interval_s = max(1.0, interval_s)
    process = psutil.Process()

    def _run():
        try:
            process.cpu_percent(interval=None)
        except Exception:
            pass
        while True:
            try:
                rss_mb = process.memory_info().rss / (1024.0 * 1024.0)
                cpu_pct = process.cpu_percent(interval=None)
                io_rate = "n/a"
                io_wait_ms = -1.0
                try:
                    counters = process.io_counters()
                    read_bytes = counters.read_bytes
                    write_bytes = counters.write_bytes
                    # Use delta from last sample (interval_s gap) instead of
                    # sleeping 50ms mid-loop — the sleep wasted 50ms of thread
                    # time and held GIL briefly on each psutil call boundary.
                    if hasattr(_run, '_prev_io'):
                        prev_r, prev_w, prev_t = _run._prev_io
                        dt_s = time.monotonic() - prev_t
                        if dt_s > 0.1:
                            read_bps = max(0, read_bytes - prev_r) / dt_s
                            write_bps = max(0, write_bytes - prev_w) / dt_s
                            io_rate = f"read={read_bps/1024.0:.1f}KB/s write={write_bps/1024.0:.1f}KB/s"
                    _run._prev_io = (read_bytes, write_bytes, time.monotonic())
                except Exception:
                    pass

                pagefaults = -1
                try:
                    if hasattr(process, "memory_full_info"):
                        memf = process.memory_full_info()
                        pagefaults = int(getattr(memf, "pfaults", -1))
                except Exception:
                    pass

                logger.info(
                    "resource-summary cpu=%.1f%% rss=%.1fMB io=%s io_wait_ms=%.2f pagefaults=%d platform=%s",
                    cpu_pct,
                    rss_mb,
                    io_rate,
                    io_wait_ms,
                    pagefaults,
                    platform.system(),
                    extra={
                        "component": "ui" if process_role == "main" else "download",
                        "process_role": process_role,
                    },
                )
            except Exception:
                pass
            time.sleep(interval_s)

    th = threading.Thread(target=_run, name=f"diag-resource-{process_role}", daemon=True)
    th.start()


class DownloadProgressAggregator:
    def __init__(self, logger_: logging.Logger, interval_seconds: float = 2.0):
        self.logger = logger_
        self.interval_seconds = max(0.5, float(interval_seconds))
        self._lock = threading.Lock()
        self._state: Dict[str, Dict[str, float]] = {}

    def update(
        self,
        *,
        key: str,
        response_length: int,
        bytes_received: int,
        queue_size: int = -1,
        active_tasks: int = -1,
        disk_write_ms: float = -1.0,
        retries: int = 0,
        study_uid: str = "-",
        series_uid: str = "-",
        download_job_id: str = "-",
    ) -> None:
        now = time.monotonic()
        with self._lock:
            state = self._state.setdefault(
                key,
                {
                    "last_t": now,
                    "last_bytes": 0.0,
                    "first_t": now,
                    "first_bytes": 0.0,
                    "retries": 0.0,
                },
            )
            state["retries"] = float(retries)
            dt = now - float(state["last_t"])
            if dt < self.interval_seconds and bytes_received < response_length:
                return

            last_bytes = float(state["last_bytes"])
            throughput = (bytes_received - last_bytes) / dt if dt > 0 else 0.0
            pct = (100.0 * bytes_received / response_length) if response_length > 0 else 0.0

            self.logger.info(
                "download-summary key=%s progress=%.1f%% bytes=%d/%d throughput=%.1fKB/s queue=%s active=%s disk_write_ms=%.2f retries=%d",
                key,
                pct,
                bytes_received,
                response_length,
                throughput / 1024.0,
                queue_size,
                active_tasks,
                disk_write_ms,
                int(state["retries"]),
                extra={
                    "component": "download",
                    "study_uid": study_uid,
                    "series_uid": series_uid,
                    "download_job_id": download_job_id,
                },
            )

            state["last_t"] = now
            state["last_bytes"] = float(bytes_received)

            if bytes_received >= response_length:
                self._state.pop(key, None)
