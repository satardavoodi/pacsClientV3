"""Background series-file warm at patient open (WU-1, 2026-08-08).

Why: the viewer's switch-time header scan (`image_io._read_header_stubs`)
re-probes every instance file of a series. On the FIRST touch after boot the
per-file cost is dominated by the antivirus' on-open scan + cold disk I/O —
live patient 53417 (2026-08-08 13:57): 444-file CT series probed at
40.5 ms/file; the adaptive 8-thread pool only reaches ~2.3x (AV-bound, bench
2026-08-08: seq 23.1 -> t8 9.8 -> t24 9.8 ms/file), so series 202 took ~8.6 s
to reach the viewport. The SAME probe on warm files is 0.88 ms/file (~0.4 s
for the whole series) and threads add nothing.

Fix: at patient open, a fire-and-forget daemon thread opens + reads the head
of every on-disk instance file of the opened studies. The open() pays the
one-time AV verdict + pulls the header bytes into the OS cache OFF the
critical path, overlapped with the open pipeline and the user's think time.
The switch-time scan itself is UNTOUCHED — it still reads and verifies every
file, it just hits warm caches.

Safety: strictly read-only; budget- and time-capped; every failure is
swallowed (a warm failure must never affect opening a patient). One warm run
per study-set at a time.

Kill switch: ``AIPACS_SERIES_FILE_WARM=0``.
Tunables: ``AIPACS_SERIES_FILE_WARM_CHUNK_KB`` (head bytes per file, default
256), ``AIPACS_SERIES_FILE_WARM_MAX_FILES`` (default 4000),
``AIPACS_SERIES_FILE_WARM_MAX_SECONDS`` (default 30),
``AIPACS_SERIES_FILE_WARM_WORKERS`` (default 8).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_active_lock = threading.Lock()
_active_keys: set[str] = set()


def _enabled() -> bool:
    return (os.environ.get("AIPACS_SERIES_FILE_WARM", "1") or "1").strip() != "0"


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip() or default)
    except Exception:
        return default


def _iter_series_files(study_paths):
    """Yield instance files under <study>/<series>/ dirs, series dir by series
    dir (sorted for determinism). Never raises."""
    for study_path in study_paths:
        try:
            # A blank path would resolve to the CURRENT DIRECTORY — never
            # walk it (caught by test_missing_and_garbage_paths_are_safe).
            if not study_path or not str(study_path).strip():
                continue
            study_dir = Path(study_path)
            if not study_dir.is_dir():
                continue
            for series_dir in sorted(study_dir.iterdir()):
                if not series_dir.is_dir():
                    continue
                try:
                    for f in sorted(series_dir.iterdir()):
                        if f.is_file():
                            yield f
                except OSError:
                    continue
        except Exception:
            continue


def _warm_paths(study_paths, *, chunk_bytes: int, max_files: int,
                max_seconds: float, workers: int) -> dict:
    """Synchronous core: open + read the head of each file. Returns stats.
    Read-only; per-file errors are ignored."""
    stats = {"files": 0, "bytes": 0, "elapsed_ms": 0.0, "capped": False}
    start = time.perf_counter()

    def _touch(path: Path) -> tuple[int, int]:
        try:
            with open(path, "rb") as fh:
                data = fh.read(chunk_bytes)
            return 1, len(data)
        except OSError:
            return 0, 0

    try:
        from concurrent.futures import ThreadPoolExecutor
        pending = []
        with ThreadPoolExecutor(max_workers=max(1, workers),
                                thread_name_prefix="serieswarm") as ex:
            for f in _iter_series_files(study_paths):
                if stats["files"] + len(pending) >= max_files:
                    stats["capped"] = True
                    break
                if (time.perf_counter() - start) >= max_seconds:
                    stats["capped"] = True
                    break
                pending.append(ex.submit(_touch, f))
            for fut in pending:
                try:
                    n, b = fut.result(timeout=max(1.0, max_seconds))
                except Exception:
                    n, b = 0, 0
                stats["files"] += n
                stats["bytes"] += b
    except Exception:
        logger.debug("[SERIES_FILE_WARM] pool failed", exc_info=True)
    stats["elapsed_ms"] = (time.perf_counter() - start) * 1000.0
    return stats


def warm_study_series_async(study_paths) -> bool:
    """Fire-and-forget warm of every on-disk instance file under the given
    study dirs. Returns True when a warm thread was started."""
    if not _enabled():
        return False
    paths = [str(p) for p in (study_paths or []) if p]
    if not paths:
        return False
    key = "|".join(sorted(paths))
    with _active_lock:
        if key in _active_keys:
            return False
        _active_keys.add(key)

    chunk = max(4, _env_int("AIPACS_SERIES_FILE_WARM_CHUNK_KB", 256)) * 1024
    max_files = max(1, _env_int("AIPACS_SERIES_FILE_WARM_MAX_FILES", 4000))
    max_seconds = float(max(1, _env_int("AIPACS_SERIES_FILE_WARM_MAX_SECONDS", 30)))
    workers = max(1, _env_int("AIPACS_SERIES_FILE_WARM_WORKERS", 8))

    def _run() -> None:
        try:
            stats = _warm_paths(paths, chunk_bytes=chunk, max_files=max_files,
                                max_seconds=max_seconds, workers=workers)
            logger.info(
                "[SERIES_FILE_WARM] files=%d bytes=%.1fMB elapsed=%.0fms "
                "capped=%s studies=%d",
                stats["files"], stats["bytes"] / 1e6, stats["elapsed_ms"],
                stats["capped"], len(paths),
            )
        except Exception:
            logger.debug("[SERIES_FILE_WARM] warm failed", exc_info=True)
        finally:
            with _active_lock:
                _active_keys.discard(key)

    threading.Thread(target=_run, name="series-file-warm", daemon=True).start()
    return True


__all__ = ["warm_study_series_async"]
