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

For Local patient opens, the catalog/inventory pipeline is the sole file
owner. The warmer skips those exact series directories instead of racing the
ordered legacy scan or re-reading every file of a producer-indexed series.
Server/unknown opens keep the original raw head warm.

Kill switch: ``AIPACS_SERIES_FILE_WARM=0``.
Tunables: ``AIPACS_SERIES_FILE_WARM_CHUNK_KB`` (head bytes per file, default
256), ``AIPACS_SERIES_FILE_WARM_MAX_FILES`` (default 4000),
``AIPACS_SERIES_FILE_WARM_MAX_SECONDS`` (default 30),
``AIPACS_SERIES_FILE_WARM_WORKERS`` (default 8).
Rollback the ordered Local owner with ``AIPACS_LOCAL_ORDERED_INVENTORY=0``;
that restores the prior shared fact-warm route. The older fact route retains
its own ``AIPACS_LOCAL_PIXEL_FACT_WARM=0`` switch.
``AIPACS_LOCAL_INDEXED_FILE_WARM=1`` restores the former whole-file warm for
producer-indexed Local series if field evidence requires it.
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


def _pixel_fact_warm_enabled() -> bool:
    return (os.environ.get("AIPACS_LOCAL_PIXEL_FACT_WARM", "1") or "1").strip() != "0"


def _ordered_local_inventory_enabled() -> bool:
    return (os.environ.get("AIPACS_LOCAL_ORDERED_INVENTORY", "1") or "1").strip() != "0"


def _local_indexed_file_warm_enabled() -> bool:
    return (os.environ.get("AIPACS_LOCAL_INDEXED_FILE_WARM", "0") or "0").strip() == "1"


def prime_dicom_pixel_fact(path: Path):
    """Lazy bridge to keep this background helper cheap to import."""
    from PacsClient.utils.dicom_displayability import prime_dicom_pixel_fact as prime
    return prime(path)


def indexed_series_pixel_inventory(series: dict):
    """Lazy bridge for strict revision-bound producer-index admission."""
    from PacsClient.utils.dicom_displayability import indexed_series_pixel_inventory as resolve
    return resolve(series)


def _pixel_fact_series_paths(local_series) -> set[str]:
    """Select only Local series that cannot use the trusted producer index."""
    if not _pixel_fact_warm_enabled():
        return set()
    selected = set()
    for series in local_series or ():
        if not isinstance(series, dict):
            continue
        raw_path = str(series.get("series_path") or "").strip()
        if not raw_path:
            continue
        try:
            indexed = indexed_series_pixel_inventory(series)
        except Exception:
            indexed = None
        if indexed is None:
            selected.add(os.path.normcase(os.path.abspath(raw_path)))
    return selected


def _local_series_warm_plan(local_series) -> tuple[set[str], set[str], set[str]]:
    """Partition Local series into raw, fact-prime and catalog-owned paths."""
    raw, facts, delegated = set(), set(), set()
    ordered_owner = _ordered_local_inventory_enabled()
    fact_warm = _pixel_fact_warm_enabled()
    for series in local_series or ():
        if not isinstance(series, dict):
            continue
        raw_path = str(series.get("series_path") or "").strip()
        if not raw_path:
            continue
        path = os.path.normcase(os.path.abspath(raw_path))
        try:
            indexed = indexed_series_pixel_inventory(series)
        except Exception:
            indexed = None
        if indexed is not None and _local_indexed_file_warm_enabled():
            raw.add(path)
        elif indexed is not None:
            delegated.add(path)
        elif ordered_owner:
            delegated.add(path)
        elif fact_warm:
            facts.add(path)
        else:
            raw.add(path)
    return raw, facts, delegated


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip() or default)
    except Exception:
        return default


def _iter_series_files(study_paths, *, excluded_series_paths=()):
    """Yield instance files under <study>/<series>/ dirs, series dir by series
    dir (sorted for determinism). Never raises."""
    excluded = {
        os.path.normcase(os.path.abspath(str(path)))
        for path in (excluded_series_paths or ()) if str(path or "").strip()
    }
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
                if os.path.normcase(os.path.abspath(series_dir)) in excluded:
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
                max_seconds: float, workers: int,
                pixel_fact_series_paths=(), delegated_series_paths=()) -> dict:
    """Synchronous core: open + read the head of each file. Returns stats.
    Read-only; per-file errors are ignored."""
    stats = {"files": 0, "bytes": 0, "fact_files": 0,
             "delegated_series": len(set(delegated_series_paths or ())),
             "elapsed_ms": 0.0, "capped": False}
    start = time.perf_counter()
    fact_series = {
        os.path.normcase(os.path.abspath(str(path)))
        for path in (pixel_fact_series_paths or ()) if str(path or "").strip()
    }

    def _touch(path: Path) -> tuple[int, int, int]:
        try:
            parent = os.path.normcase(os.path.abspath(path.parent))
            if (parent in fact_series
                    and os.path.normcase(path.suffix) == ".dcm"):
                prime_dicom_pixel_fact(path)
                return 1, 0, 1
            with open(path, "rb") as fh:
                data = fh.read(chunk_bytes)
            return 1, len(data), 0
        except Exception:
            return 0, 0, 0

    try:
        from concurrent.futures import ThreadPoolExecutor
        pending = []
        with ThreadPoolExecutor(max_workers=max(1, workers),
                                thread_name_prefix="serieswarm") as ex:
            for f in _iter_series_files(
                study_paths, excluded_series_paths=delegated_series_paths,
            ):
                if stats["files"] + len(pending) >= max_files:
                    stats["capped"] = True
                    break
                if (time.perf_counter() - start) >= max_seconds:
                    stats["capped"] = True
                    break
                pending.append(ex.submit(_touch, f))
            for fut in pending:
                try:
                    n, b, fact = fut.result(timeout=max(1.0, max_seconds))
                except Exception:
                    n, b, fact = 0, 0, 0
                stats["files"] += n
                stats["bytes"] += b
                stats["fact_files"] += fact
    except Exception:
        logger.debug("[SERIES_FILE_WARM] pool failed", exc_info=True)
    stats["elapsed_ms"] = (time.perf_counter() - start) * 1000.0
    return stats


def warm_study_series_async(study_paths, *, local_series=None) -> bool:
    """Fire-and-forget warm of every on-disk instance file under the given
    study dirs. Returns True when a warm thread was started."""
    if not _enabled():
        return False
    paths = [str(p) for p in (study_paths or []) if p]
    if not paths:
        return False
    if local_series is None:
        raw_series = set()
        fact_series = set()
        delegated_series = set()
    else:
        raw_series, fact_series, delegated_series = _local_series_warm_plan(local_series)
        if not raw_series and not fact_series:
            logger.info(
                "[SERIES_FILE_WARM] skipped reason=local_catalog_owned "
                "studies=%d series=%d",
                len(paths), len(delegated_series),
            )
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
                                max_seconds=max_seconds, workers=workers,
                                pixel_fact_series_paths=fact_series,
                                delegated_series_paths=delegated_series)
            logger.info(
                "[SERIES_FILE_WARM] files=%d bytes=%.1fMB elapsed=%.0fms "
                "capped=%s studies=%d fact_files=%d delegated_series=%d",
                stats["files"], stats["bytes"] / 1e6, stats["elapsed_ms"],
                stats["capped"], len(paths), stats["fact_files"],
                stats["delegated_series"],
            )
        except Exception:
            logger.debug("[SERIES_FILE_WARM] warm failed", exc_info=True)
        finally:
            with _active_lock:
                _active_keys.discard(key)

    threading.Thread(target=_run, name="series-file-warm", daemon=True).start()
    return True


__all__ = ["warm_study_series_async"]
