"""Centralized thumbnail store — one in-memory LRU cache, two access points.

Pattern
-------
Download write path   :  ThumbnailStore.instance().put(study_uid, series_number, png_bytes)
Viewer read path      :  data = ThumbnailStore.instance().get_bytes(study_uid, series_number)

Thread safety
-------------
``put()`` and ``get_bytes()`` are fully thread-safe (single threading.Lock).
Both may be called from any thread (download worker, Qt main, QThreadPool worker, etc.).

Eviction
--------
LRU OrderedDict, bounded by ``max_entries`` (300) AND ``max_bytes`` (50 MB).
When either limit is exceeded the oldest entry is evicted first.

Disk fallback
-------------
If a requested entry is not in the bytes dict, ``get_bytes()`` checks::

    THUMBNAIL_PATH / study_uid / {series_number}.png

and automatically populates the cache from disk so the next caller is served
from memory.

QPixmap helper
--------------
``make_pixmap_from_bytes(data)`` converts raw PNG/JPEG bytes to a QPixmap
**without** a disk round-trip.  Must be called on the Qt main thread because
QPixmap construction is not thread-safe.  For background decoding, use
QImage.loadFromData() (any thread) followed by QPixmap.fromImage() (main thread).
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Module-level constants (can be overridden before first instance() call).
# ---------------------------------------------------------------------------
_STORE_MAX_ENTRIES: int = 300
_STORE_MAX_BYTES: int = 50 * 1024 * 1024   # 50 MB


class ThumbnailStore:
    """Singleton LRU bytes-cache for series thumbnails.

    Use ``ThumbnailStore.instance()`` everywhere.  Never instantiate directly.
    """

    _singleton: Optional["ThumbnailStore"] = None
    _singleton_lock: threading.Lock = threading.Lock()

    # ---------------------------------------------------------------------- factory
    @classmethod
    def instance(cls) -> "ThumbnailStore":
        """Return the process-wide singleton, creating it on first call."""
        if cls._singleton is None:
            with cls._singleton_lock:
                if cls._singleton is None:
                    cls._singleton = cls()
        return cls._singleton

    # ---------------------------------------------------------------------- init
    def __init__(
        self,
        max_entries: int = _STORE_MAX_ENTRIES,
        max_bytes: int = _STORE_MAX_BYTES,
    ) -> None:
        # (study_uid, series_number) → bytes
        self._cache: OrderedDict[tuple, bytes] = OrderedDict()
        self._total_bytes: int = 0
        self._max_bytes: int = int(max_bytes)
        self._max_entries: int = int(max_entries)
        self._lock: threading.Lock = threading.Lock()

    # ---------------------------------------------------------------------- write
    def put(self, study_uid: str, series_number: str, data: bytes) -> None:
        """Insert or refresh an entry.  Evicts oldest entries when limits exceeded.

        Thread-safe; may be called from any thread.
        """
        if not data:
            return
        key = (str(study_uid), str(series_number))
        size = len(data)
        with self._lock:
            # Refresh LRU position if already present.
            if key in self._cache:
                old = self._cache.pop(key)
                self._total_bytes -= len(old)
            # Evict until within both limits.
            while self._cache and (
                self._total_bytes + size > self._max_bytes
                or len(self._cache) >= self._max_entries
            ):
                _, oldest_data = self._cache.popitem(last=False)
                self._total_bytes -= len(oldest_data)
            self._cache[key] = data
            self._total_bytes += size

    # ---------------------------------------------------------------------- read
    def get_bytes(self, study_uid: str, series_number: str) -> Optional[bytes]:
        """Return cached bytes, or try to read from disk on a cache miss.

        Thread-safe; may be called from any thread.
        Returns ``None`` if neither memory cache nor disk has the thumbnail.
        """
        key = (str(study_uid), str(series_number))
        with self._lock:
            data = self._cache.get(key)
            if data is not None:
                self._cache.move_to_end(key)   # LRU refresh
                return data
        # Disk fallback — outside the lock so we don't block other callers.
        try:
            from PacsClient.utils.config import THUMBNAIL_PATH  # type: ignore
            path: Path = THUMBNAIL_PATH / str(study_uid) / f"{series_number}.png"
            if path.exists():
                disk_data: bytes = path.read_bytes()
                if disk_data:
                    self.put(study_uid, series_number, disk_data)  # warm cache
                    return disk_data
        except Exception:
            pass
        return None

    def has(self, study_uid: str, series_number: str) -> bool:
        """Non-mutating fast membership check (memory only, no disk probe)."""
        key = (str(study_uid), str(series_number))
        with self._lock:
            return key in self._cache

    def clear(self) -> None:
        """Empty the entire in-memory cache."""
        with self._lock:
            self._cache.clear()
            self._total_bytes = 0

    @property
    def stats(self) -> dict:
        """Return a snapshot of current cache statistics."""
        with self._lock:
            return {
                "entries": len(self._cache),
                "bytes_used": self._total_bytes,
                "bytes_max": self._max_bytes,
                "utilization_pct": round(
                    100.0 * self._total_bytes / self._max_bytes, 1
                ) if self._max_bytes > 0 else 0.0,
            }


# ---------------------------------------------------------------------------
# Convenience helper — main-thread only
# ---------------------------------------------------------------------------
def make_pixmap_from_bytes(data: bytes):
    """Convert raw PNG/JPEG bytes to a QPixmap without a disk round-trip.

    MUST be called on the Qt main thread.
    Returns a valid QPixmap on success, or a null QPixmap on failure.
    """
    try:
        from PySide6.QtGui import QImage, QPixmap  # type: ignore
        img = QImage()
        if img.loadFromData(data) and not img.isNull():
            return QPixmap.fromImage(img)
        return QPixmap()
    except Exception:
        return None
