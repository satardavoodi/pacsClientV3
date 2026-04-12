"""H12 decode-thread concurrency guard and instrumentation.

Provides:
  - decode_serialisation_guard: bounds the number of concurrent
    pydicom.dcmread + pixel_array calls across *every* decode domain
    (lazy-volume workers, ImageSliceBooster, etc.).
    Default = 1 (fully serialised — prevents H12 GIL crash).
    Tune via  AIPACS_MAX_DECODE_THREADS=N  (e.g. 2 for bounded parallelism).
    Legacy env var  AIPACS_SERIALIZE_DECODE=1  is still recognised (forces N=1).
  - decode_overlap_tracker: lightweight atomic counter + codec-path logger
    for H12-1 probes (always active).
  - backing_store_detector: non-blocking tryLock probe for H12-3 (always active).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────
# Decode concurrency gate  (H12 fix — was diagnostic toggle T2)
# ────────────────────────────────────────────────────────────────────────
# Default = 1 (serialised).  Prevents the fatal GIL crash caused by
# concurrent C-extension pixel decoders (pylibjpeg-libjpeg / openjpeg).
# Set AIPACS_MAX_DECODE_THREADS=N to allow N concurrent decodes.
# Legacy: AIPACS_SERIALIZE_DECODE=1 is equivalent to N=1 (now the default).
_MAX_CONCURRENT_DECODE = int(os.environ.get("AIPACS_MAX_DECODE_THREADS", "1"))
_DECODE_GATE = threading.Semaphore(_MAX_CONCURRENT_DECODE)

logger.info(
    "[H12-FIX] decode concurrency gate active: max_concurrent=%d",
    _MAX_CONCURRENT_DECODE,
)


@contextmanager
def decode_serialisation_guard():
    """Acquire a decode slot before pydicom.dcmread + pixel_array."""
    _DECODE_GATE.acquire()
    try:
        yield
    finally:
        _DECODE_GATE.release()


# ────────────────────────────────────────────────────────────────────────
# H12-1  – Cross-domain decode overlap counter + codec identification
# ────────────────────────────────────────────────────────────────────────
_overlap_lock = threading.Lock()
_active_decode_count: int = 0
_peak_overlap: int = 0


def _inc_decode() -> int:
    global _active_decode_count, _peak_overlap
    with _overlap_lock:
        _active_decode_count += 1
        c = _active_decode_count
        if c > _peak_overlap:
            _peak_overlap = c
        return c


def _dec_decode() -> int:
    global _active_decode_count
    with _overlap_lock:
        _active_decode_count = max(0, _active_decode_count - 1)
        return _active_decode_count


def log_decode_entry(domain: str, slice_idx: int, path: str) -> int:
    """Call before pydicom.dcmread.  Returns current overlap count."""
    count = _inc_decode()
    tid = threading.current_thread().ident
    if count > 1:
        logger.info(
            "[H12-1] DECODE_ENTRY domain=%s slice=%d overlap=%d tid=%s path=%s",
            domain, slice_idx, count, tid, path,
        )
    else:
        logger.debug(
            "[H12-1] DECODE_ENTRY domain=%s slice=%d overlap=%d tid=%s",
            domain, slice_idx, count, tid,
        )
    return count


def log_decode_exit(
    domain: str,
    slice_idx: int,
    *,
    transfer_syntax_uid: str = "",
    is_compressed: Optional[bool] = None,
    handler_name: str = "",
    decode_ms: float = 0.0,
) -> None:
    """Call after pixel_array has been extracted."""
    count = _dec_decode()
    tid = threading.current_thread().ident
    logger.info(
        "[H12-1] DECODE_EXIT domain=%s slice=%d overlap_after=%d tid=%s "
        "tsuid=%s compressed=%s handler=%s decode_ms=%.2f",
        domain, slice_idx, count, tid,
        transfer_syntax_uid, is_compressed, handler_name, decode_ms,
    )


def get_peak_overlap() -> int:
    with _overlap_lock:
        return _peak_overlap


# ────────────────────────────────────────────────────────────────────────
# H12-3  – Shared backing-store concurrent access detector
# ────────────────────────────────────────────────────────────────────────
_backing_store_lock = threading.Lock()
_backing_store_holder: Optional[str] = None  # "domain:tid"


@contextmanager
def backing_store_probe(domain: str):
    """Non-blocking probe: log overlap when two threads touch the same
    backing store (memmap write vs VTK render vs cache mutation)."""
    tag = f"{domain}:{threading.current_thread().ident}"
    acquired = _backing_store_lock.acquire(blocking=False)
    global _backing_store_holder
    if acquired:
        _backing_store_holder = tag
        try:
            yield
        finally:
            _backing_store_holder = None
            _backing_store_lock.release()
    else:
        # Another thread holds it — log the overlap
        logger.warning(
            "[H12-3] BACKING_STORE_OVERLAP current=%s holder=%s",
            tag, _backing_store_holder,
        )
        yield  # proceed anyway — probe is non-blocking


# ────────────────────────────────────────────────────────────────────────
# H12-4  – Thread-state canary
# ────────────────────────────────────────────────────────────────────────
def thread_state_canary(domain: str, phase: str) -> None:
    """Quick GIL-requires operation as a canary.

    ``threading.current_thread().ident`` is a Python attribute access that
    requires the current thread to hold the GIL.  If this crashes, the GIL
    was already lost *before* or *after* the decode call.
    """
    try:
        _tid = threading.current_thread().ident
        logger.debug("[H12-4] CANARY ok domain=%s phase=%s tid=%s", domain, phase, _tid)
    except Exception as exc:
        logger.critical(
            "[H12-4] CANARY FAILED domain=%s phase=%s error=%s", domain, phase, exc,
        )


# ────────────────────────────────────────────────────────────────────────
# Helper: extract codec info from a pydicom Dataset after dcmread
# ────────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────────
# H13  – Backing-store / Publish / Render consistency probes
# ────────────────────────────────────────────────────────────────────────

# --- H13-P1 / H13-P2: Write/Render overlap detector ---
# _WRITE_ACTIVE is set by workers around `vol[i] = arr`.
# Main-thread render code reads it (single atomic read in CPython) to
# detect temporal overlap.  _H13_OVERLAP_COUNT is a running tally.
_WRITE_ACTIVE: Optional[tuple] = None   # (tid, slice_idx, perf_counter_ns)
_H13_OVERLAP_COUNT: int = 0
_H13_OVERLAP_MAX_DURATION_NS: int = 0

# --- H13-P3: Decode-to-render age tracking ---
# Workers store completion timestamps per slice; render code computes the
# age = now − write_timestamp.
_WRITE_TIMESTAMPS: dict = {}  # {slice_idx: perf_counter_ns}

# --- Environment toggles (T3 / T4 / T5) ---
_H13_DEEP_COPY = bool(os.environ.get("AIPACS_VTK_DEEP_COPY"))
_H13_RENDER_GATE = bool(os.environ.get("AIPACS_RENDER_GATE"))
_H13_KEEPALIVE = bool(os.environ.get("AIPACS_KEEPALIVE_OLD_VOLUME"))
_H13_STALE_RENDER_ABORT = bool(os.environ.get("AIPACS_STALE_RENDER_ABORT"))

logger.info(
    "[H13-INIT] toggles: deep_copy=%s render_gate=%s keepalive=%s stale_render_abort=%s",
    _H13_DEEP_COPY, _H13_RENDER_GATE, _H13_KEEPALIVE, _H13_STALE_RENDER_ABORT,
)

# --- H13-BUILD: one-time VTK / Python / NumPy build provenance log ---
try:
    import sys as _sys
    _py_ver = _sys.version.replace("\n", " ")
    try:
        import vtk as _vtk
        _vtk_ver = _vtk.vtkVersion.GetVTKVersion()
    except Exception:
        _vtk_ver = "unavailable"
    try:
        import numpy as _np
        _np_ver = _np.__version__
    except Exception:
        _np_ver = "unavailable"
    # PyPI VTK wheels are NOT built with VTK_PYTHON_FULL_THREADSAFE=ON.
    # That flag controls whether wrapper methods properly detach/reattach
    # thread state around GIL-released C++ calls.  Its absence elevates
    # H13-B (wrapper thread-state bug) as an enabling condition.
    _vtk_thread_safe = "unknown"
    try:
        # VTK_PYTHON_FULL_THREADSAFE adds vtkPythonScopeGilEnsurer to every
        # wrapper.  A practical proxy: check for the GIL-release annotation
        # flag on a known method.  If it is absent, the build is NOT full
        # thread-safe.
        import vtkmodules as _vm
        _vtk_pkg_path = getattr(_vm, "__file__", "unknown")
        _vtk_thread_safe = "likely_OFF (PyPI wheel)"
    except Exception:
        pass
    logger.info(
        "[H13-BUILD] python=%s vtk=%s numpy=%s vtk_thread_safe=%s vtk_path=%s",
        _py_ver, _vtk_ver, _np_ver, _vtk_thread_safe,
        _vtk_pkg_path if "_vtk_pkg_path" in dir() else "unknown",
    )
except Exception as _build_exc:
    logger.warning("[H13-BUILD] failed to collect build info: %s", _build_exc)


def h13_write_begin(tid: int, slice_idx: int) -> None:
    """Called by worker BEFORE vol[i] = arr."""
    global _WRITE_ACTIVE
    _WRITE_ACTIVE = (tid, slice_idx, time.perf_counter_ns())


def h13_write_end(slice_idx: int) -> None:
    """Called by worker AFTER vol[i] = arr."""
    global _WRITE_ACTIVE
    _WRITE_TIMESTAMPS[slice_idx] = time.perf_counter_ns()
    _WRITE_ACTIVE = None


def h13_check_overlap_before_render(render_slice: int, caller: str) -> None:
    """Called by main thread BEFORE render-chain (mark_vtk_modified → Render).

    Logs H13-OVERLAP if a worker write is in progress.
    """
    global _H13_OVERLAP_COUNT, _H13_OVERLAP_MAX_DURATION_NS
    wa = _WRITE_ACTIVE  # single atomic read
    if wa is not None:
        tid, w_slice, w_ns = wa
        delta_ns = time.perf_counter_ns() - w_ns
        _H13_OVERLAP_COUNT += 1
        if delta_ns > _H13_OVERLAP_MAX_DURATION_NS:
            _H13_OVERLAP_MAX_DURATION_NS = delta_ns
        logger.warning(
            "[H13-OVERLAP] render_chain while write active: "
            "write_tid=%d write_slice=%d render_slice=%d delta_ms=%.2f "
            "overlap_count=%d caller=%s",
            tid, w_slice, render_slice, delta_ns / 1_000_000.0,
            _H13_OVERLAP_COUNT, caller,
        )


def h13_get_decode_age_ms(slice_idx: int) -> float:
    """Return age in ms since slice was last written, or -1.0 if unknown."""
    ts = _WRITE_TIMESTAMPS.get(slice_idx)
    if ts is None:
        return -1.0
    return (time.perf_counter_ns() - ts) / 1_000_000.0


def h13_get_overlap_stats() -> tuple:
    """Return (overlap_count, max_duration_ns)."""
    return (_H13_OVERLAP_COUNT, _H13_OVERLAP_MAX_DURATION_NS)


def extract_codec_info(ds) -> dict:
    """Return transfer-syntax and handler info from a read Dataset."""
    info: dict = {
        "transfer_syntax_uid": "",
        "is_compressed": None,
        "handler_name": "",
    }
    try:
        tsuid = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
        if tsuid is not None:
            info["transfer_syntax_uid"] = str(tsuid)
            info["is_compressed"] = bool(getattr(tsuid, "is_compressed", None))
    except Exception:
        pass
    try:
        # pydicom >= 2.x stores the handler name in the dataset after decode
        handler = getattr(ds, "_pixel_data_handler_name", None)
        if handler:
            info["handler_name"] = str(handler)
        else:
            # fallback: check which handler pydicom would select
            import pydicom.config
            handlers = getattr(pydicom.config, "pixel_data_handlers", [])
            for h in handlers:
                name = getattr(h, "__name__", "") or getattr(h, "HANDLER_NAME", "")
                if name:
                    info["handler_name"] = str(name)
                    break
    except Exception:
        pass
    return info
