"""
Disk Pixel Cache (B3.12)
========================
L2 persistent cache for decoded DICOM pixel arrays.  Eliminates the need to
re-decode slices when reopening a previously-viewed series.

Cache key: ``{sop_instance_uid}_{transfer_syntax_uid_hash}.npy``
Cache location: ``{USER_DATA_ROOT}/cache/pixel_cache/{study_uid_hash}/``

Design:
- numpy save/load for fast binary I/O (mmap-friendly)
- LRU eviction by last-access time when cache exceeds ``max_size_bytes``
- Corruption-safe: verify array shape/dtype on load, delete on mismatch
- Thread-safe: one lock for metadata, no lock for file I/O (OS handles it)
- Async write: disk writes are fire-and-forget on a background thread

Inspired by Orthanc Web Viewer disk cache pattern.
"""

from __future__ import annotations

import hashlib
import logging
import os
import struct
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────
_DEFAULT_MAX_SIZE_MB = 2048  # 2 GB
_CACHE_SUBDIR = "cache/pixel_cache"
_HEADER_MAGIC = b"APDC"  # AiPacs Disk Cache
_HEADER_VERSION = 1
_HEADER_FMT = "<4s B B 2I"  # magic(4) + version(1) + dtype_code(1) + rows(4) + cols(4) = 14 bytes
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)

_DTYPE_MAP = {
    0: np.int16,
    1: np.uint16,
    2: np.float32,
    3: np.uint8,
}
_DTYPE_REV = {v: k for k, v in _DTYPE_MAP.items()}


def _uid_hash(uid: str) -> str:
    """Short hash of a DICOM UID for filesystem-safe directory names."""
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()[:16]


class DiskPixelCache:
    """Thread-safe LRU disk cache for decoded pixel arrays."""

    def __init__(
        self,
        user_data_root: Path,
        max_size_mb: int = _DEFAULT_MAX_SIZE_MB,
    ):
        self._root = user_data_root / _CACHE_SUBDIR
        self._max_size_bytes = max_size_mb * 1024 * 1024
        self._lock = threading.Lock()
        # OrderedDict: cache_key -> (file_path, size_bytes, last_access)
        self._index: OrderedDict[str, Tuple[Path, int, float]] = OrderedDict()
        self._total_bytes = 0
        self._write_executor = threading.Thread(target=lambda: None, daemon=True)
        self._pending_writes: list = []
        self._write_lock = threading.Lock()
        self._initialized = False

    def initialize(self) -> None:
        """Scan existing cache files and build index. Call once at startup."""
        if self._initialized:
            return
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            total = 0
            entries = []
            for study_dir in self._root.iterdir():
                if not study_dir.is_dir():
                    continue
                for cache_file in study_dir.iterdir():
                    if cache_file.suffix == ".apc":
                        try:
                            stat = cache_file.stat()
                            entries.append((
                                cache_file.stem,
                                cache_file,
                                stat.st_size,
                                stat.st_mtime,
                            ))
                            total += stat.st_size
                        except OSError:
                            pass
            # Sort by mtime (oldest first) for LRU
            entries.sort(key=lambda e: e[3])
            with self._lock:
                for key, path, size, mtime in entries:
                    self._index[key] = (path, size, mtime)
                self._total_bytes = total
            self._initialized = True
            logger.info(
                "[B3.12] Disk pixel cache initialized: %d entries, %.1f MB, root=%s",
                len(entries), total / (1024 * 1024), self._root,
            )
        except Exception:
            logger.exception("[B3.12] Failed to initialize disk pixel cache")
            self._initialized = True  # Don't retry

    def get(
        self,
        sop_instance_uid: str,
        study_uid: str,
        expected_shape: Optional[Tuple[int, int]] = None,
    ) -> Optional[np.ndarray]:
        """Load a cached pixel array from disk.

        Returns None on miss or corruption (corrupt files are deleted).
        """
        if not self._initialized:
            return None
        key = _uid_hash(sop_instance_uid)
        with self._lock:
            entry = self._index.get(key)
            if entry is None:
                return None
            path, size, _ = entry
            # Move to end (most recently used)
            self._index.move_to_end(key)
            self._index[key] = (path, size, time.time())

        try:
            arr = self._read_file(path, expected_shape)
            return arr
        except Exception:
            # Corrupt file — delete it
            self._remove_entry(key, path)
            return None

    def put(
        self,
        sop_instance_uid: str,
        study_uid: str,
        arr: np.ndarray,
    ) -> None:
        """Store a decoded pixel array to disk (async, fire-and-forget)."""
        if not self._initialized:
            return
        key = _uid_hash(sop_instance_uid)
        with self._lock:
            if key in self._index:
                return  # Already cached

        study_hash = _uid_hash(study_uid)
        target_dir = self._root / study_hash
        target_path = target_dir / f"{key}.apc"

        # Fire-and-forget write on background thread
        t = threading.Thread(
            target=self._write_file,
            args=(key, target_dir, target_path, study_uid, arr.copy()),
            daemon=True,
        )
        t.start()

    def clear(self) -> None:
        """Delete all cached files."""
        with self._lock:
            self._index.clear()
            self._total_bytes = 0
        try:
            import shutil
            if self._root.exists():
                shutil.rmtree(self._root)
                self._root.mkdir(parents=True, exist_ok=True)
            logger.info("[B3.12] Disk pixel cache cleared")
        except Exception:
            logger.exception("[B3.12] Failed to clear disk cache")

    def stats(self) -> dict:
        """Return cache statistics."""
        with self._lock:
            return {
                "entries": len(self._index),
                "total_mb": self._total_bytes / (1024 * 1024),
                "max_mb": self._max_size_bytes / (1024 * 1024),
            }

    # ── Private ───────────────────────────────────────────────────────

    def _write_file(
        self,
        key: str,
        target_dir: Path,
        target_path: Path,
        study_uid: str,
        arr: np.ndarray,
    ) -> None:
        """Write array to disk with custom header. Runs on background thread."""
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            dtype_code = _DTYPE_REV.get(arr.dtype.type)
            if dtype_code is None:
                # Unsupported dtype — convert to float32
                arr = arr.astype(np.float32)
                dtype_code = _DTYPE_REV[np.float32]

            rows, cols = arr.shape[:2]
            header = struct.pack(
                _HEADER_FMT,
                _HEADER_MAGIC,
                _HEADER_VERSION,
                dtype_code,
                rows,
                cols,
            )
            raw_bytes = np.ascontiguousarray(arr).tobytes()

            # Atomic write: write to temp, then rename
            tmp_path = target_path.with_suffix(".tmp")
            with open(tmp_path, "wb") as f:
                f.write(header)
                f.write(raw_bytes)
            # Atomic rename (Windows: may fail if target exists, but we checked)
            try:
                tmp_path.replace(target_path)
            except OSError:
                # Windows fallback: delete then rename
                if target_path.exists():
                    target_path.unlink()
                tmp_path.rename(target_path)

            file_size = _HEADER_SIZE + len(raw_bytes)

            with self._lock:
                self._index[key] = (target_path, file_size, time.time())
                self._index.move_to_end(key)
                self._total_bytes += file_size

            # Evict if over limit
            self._evict_if_needed()

        except Exception:
            logger.debug("[B3.12] Disk cache write failed for %s", key, exc_info=True)
            # Clean up temp file
            try:
                tmp_path = target_path.with_suffix(".tmp")
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass

    def _read_file(
        self,
        path: Path,
        expected_shape: Optional[Tuple[int, int]] = None,
    ) -> np.ndarray:
        """Read array from disk with header validation."""
        with open(path, "rb") as f:
            header_bytes = f.read(_HEADER_SIZE)
            if len(header_bytes) < _HEADER_SIZE:
                raise ValueError("truncated header")

            magic, version, dtype_code, rows, cols = struct.unpack(
                _HEADER_FMT, header_bytes
            )
            if magic != _HEADER_MAGIC:
                raise ValueError(f"bad magic: {magic!r}")
            if version != _HEADER_VERSION:
                raise ValueError(f"unsupported version: {version}")
            if dtype_code not in _DTYPE_MAP:
                raise ValueError(f"unknown dtype code: {dtype_code}")

            dtype = _DTYPE_MAP[dtype_code]
            if expected_shape and (rows, cols) != expected_shape:
                raise ValueError(
                    f"shape mismatch: file=({rows},{cols}), expected={expected_shape}"
                )

            expected_bytes = rows * cols * np.dtype(dtype).itemsize
            raw = f.read(expected_bytes)
            if len(raw) < expected_bytes:
                raise ValueError("truncated pixel data")

        arr = np.frombuffer(raw, dtype=dtype).reshape(rows, cols)
        return np.ascontiguousarray(arr)

    def _remove_entry(self, key: str, path: Path) -> None:
        """Remove a cache entry (corrupt or evicted)."""
        with self._lock:
            entry = self._index.pop(key, None)
            if entry:
                self._total_bytes -= entry[1]
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    def _evict_if_needed(self) -> None:
        """Evict oldest entries until under size limit."""
        to_remove = []
        with self._lock:
            while self._total_bytes > self._max_size_bytes and self._index:
                key, (path, size, _) = self._index.popitem(last=False)
                self._total_bytes -= size
                to_remove.append(path)

        for path in to_remove:
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        if to_remove:
            logger.debug("[B3.12] Evicted %d cache entries", len(to_remove))


# ── Module-level singleton ────────────────────────────────────────────────
_instance: Optional[DiskPixelCache] = None
_instance_lock = threading.Lock()


def get_disk_pixel_cache() -> DiskPixelCache:
    """Get or create the global disk pixel cache singleton."""
    global _instance
    if _instance is not None:
        return _instance
    with _instance_lock:
        if _instance is not None:
            return _instance
        try:
            from PacsClient.utils.data_paths import USER_DATA_ROOT
            root = Path(USER_DATA_ROOT)
        except ImportError:
            root = Path("user_data")
        _instance = DiskPixelCache(root)
        _instance.initialize()
        return _instance
