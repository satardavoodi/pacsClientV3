"""Cache manager facade — Phase 1.2 of the architecture review.

Provides a small typed surface for named LRU cache regions backed by a
single global byte budget. This is the **facade** — existing pipeline
caches (``Lightweight2DPipeline._pixel_cache``, ``_frame_cache``, etc.)
continue to work unchanged. Future phases may route those through the
manager, but Phase 1.2 only ships the facade + its unit tests.

Design
------
- Each ``CacheRegion`` is a thread-safe LRU keyed by an arbitrary hashable.
- A region has independent ``max_bytes`` and ``max_entries`` budgets;
  whichever fires first triggers eviction.
- ``CacheManager`` owns named regions and exposes a global ``stats()``
  view useful for diagnostics.
- Eviction policy is strict LRU: oldest insertion order wins.
- ``put`` re-inserts an existing key at the most-recent position
  (mirroring ``OrderedDict.move_to_end`` semantics already used by the
  pipeline).
- All operations are O(1).

Thread-safety
-------------
Every region uses a re-entrant lock around state mutations. Reads
(``get``, ``stats``) also take the lock so the LRU position update is
atomic with the lookup.

Bytes accounting
----------------
The caller supplies a ``size_bytes`` callback at region construction.
For numpy arrays use ``arr.nbytes``; for QImage use
``img.byteCount()``; for primitives use ``sys.getsizeof``. The default
``estimate_bytes`` returns 0 — meaning bytes-budget eviction never
fires and only the entry-count budget applies. This keeps the facade
usable in tests without forcing every caller to ship a sizer.

This module deliberately does no logging on the hot path. Wire R21
``[SLOT_TIMING]`` at the *caller* if you need observability.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Dict, Hashable, Iterator, Optional, Tuple


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------


SizeFn = Callable[[Any], int]


def _zero_size(_value: Any) -> int:
    return 0


# ---------------------------------------------------------------------------
# CacheRegion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegionStats:
    name: str
    entries: int
    bytes: int
    max_entries: int
    max_bytes: int
    hit_count: int
    miss_count: int
    eviction_count: int

    @property
    def hit_ratio(self) -> float:
        total = self.hit_count + self.miss_count
        if total == 0:
            return 0.0
        return self.hit_count / total


class CacheRegion:
    """A single named LRU region.

    Parameters
    ----------
    name: str
        Region identifier (used in stats and error messages).
    max_entries: int
        Hard upper bound on the number of entries. Must be >= 1.
    max_bytes: int
        Hard upper bound on the total bytes of all entries. Use
        ``0`` to disable the byte budget (entry count only).
    size_fn: callable(value) -> int
        Returns the size in bytes of a stored value. Default: 0.
    """

    __slots__ = (
        "_name",
        "_max_entries",
        "_max_bytes",
        "_size_fn",
        "_data",
        "_sizes",
        "_total_bytes",
        "_lock",
        "_hit",
        "_miss",
        "_evict",
    )

    _MISSING = object()

    def __init__(
        self,
        name: str,
        max_entries: int,
        max_bytes: int = 0,
        size_fn: Optional[SizeFn] = None,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("CacheRegion name must be a non-empty string")
        if max_entries < 1:
            raise ValueError("CacheRegion max_entries must be >= 1")
        if max_bytes < 0:
            raise ValueError("CacheRegion max_bytes must be >= 0")
        self._name = name
        self._max_entries = int(max_entries)
        self._max_bytes = int(max_bytes)
        self._size_fn: SizeFn = size_fn or _zero_size
        self._data: "OrderedDict[Hashable, Any]" = OrderedDict()
        self._sizes: Dict[Hashable, int] = {}
        self._total_bytes: int = 0
        self._lock = threading.RLock()
        self._hit = 0
        self._miss = 0
        self._evict = 0

    # Properties ----------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def max_entries(self) -> int:
        return self._max_entries

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __contains__(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._data

    # Core operations -----------------------------------------------------

    def get(self, key: Hashable, default: Any = None) -> Any:
        """Return the value for ``key`` and mark it most-recently-used."""
        with self._lock:
            if key not in self._data:
                self._miss += 1
                return default
            value = self._data.pop(key)
            self._data[key] = value  # move to end
            self._hit += 1
            return value

    def peek(self, key: Hashable, default: Any = None) -> Any:
        """Return the value for ``key`` WITHOUT changing LRU position.

        Does not increment hit/miss counters.
        """
        with self._lock:
            return self._data.get(key, default)

    def put(self, key: Hashable, value: Any) -> None:
        """Insert/replace ``key=value`` and run eviction if needed."""
        with self._lock:
            if key in self._data:
                # Replace path: drop old size, remove from order.
                old_size = self._sizes.pop(key, 0)
                self._total_bytes -= old_size
                self._data.pop(key, None)
            try:
                size = int(self._size_fn(value))
            except Exception:
                size = 0
            if size < 0:
                size = 0
            self._data[key] = value
            self._sizes[key] = size
            self._total_bytes += size
            self._evict_if_needed()

    def pop(self, key: Hashable, default: Any = _MISSING) -> Any:
        """Remove and return the value for ``key``."""
        with self._lock:
            if key not in self._data:
                if default is self._MISSING:
                    raise KeyError(key)
                return default
            value = self._data.pop(key)
            size = self._sizes.pop(key, 0)
            self._total_bytes -= size
            return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._sizes.clear()
            self._total_bytes = 0

    def reset_stats(self) -> None:
        with self._lock:
            self._hit = 0
            self._miss = 0
            self._evict = 0

    def keys(self) -> Iterator[Hashable]:
        """Snapshot of current keys in LRU order (oldest first)."""
        with self._lock:
            return iter(list(self._data.keys()))

    def stats(self) -> RegionStats:
        with self._lock:
            return RegionStats(
                name=self._name,
                entries=len(self._data),
                bytes=self._total_bytes,
                max_entries=self._max_entries,
                max_bytes=self._max_bytes,
                hit_count=self._hit,
                miss_count=self._miss,
                eviction_count=self._evict,
            )

    # Resize / reconfigure ------------------------------------------------

    def set_max_entries(self, max_entries: int) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        with self._lock:
            self._max_entries = int(max_entries)
            self._evict_if_needed()

    def set_max_bytes(self, max_bytes: int) -> None:
        if max_bytes < 0:
            raise ValueError("max_bytes must be >= 0")
        with self._lock:
            self._max_bytes = int(max_bytes)
            self._evict_if_needed()

    # Internals -----------------------------------------------------------

    def _evict_if_needed(self) -> None:
        # Caller must hold self._lock.
        while self._data and len(self._data) > self._max_entries:
            self._evict_oldest()
        if self._max_bytes > 0:
            while self._data and self._total_bytes > self._max_bytes:
                self._evict_oldest()

    def _evict_oldest(self) -> None:
        # Caller must hold self._lock.
        try:
            key, _value = self._data.popitem(last=False)
        except KeyError:  # pragma: no cover
            return
        size = self._sizes.pop(key, 0)
        self._total_bytes -= size
        self._evict += 1


# ---------------------------------------------------------------------------
# CacheManager
# ---------------------------------------------------------------------------


class CacheManager:
    """Owns a set of named ``CacheRegion``s.

    The manager is a *registry* — it does not enforce a global byte
    budget across regions. Future phases may add a global budget; for
    now each region governs itself. This matches the existing pipeline
    behaviour where ``_pixel_cache`` and ``_frame_cache`` have
    independent caps.
    """

    __slots__ = ("_regions", "_lock")

    def __init__(self) -> None:
        self._regions: Dict[str, CacheRegion] = {}
        self._lock = threading.RLock()

    def create_region(
        self,
        name: str,
        max_entries: int,
        max_bytes: int = 0,
        size_fn: Optional[SizeFn] = None,
    ) -> CacheRegion:
        """Create and register a new region. Raises if ``name`` already exists."""
        with self._lock:
            if name in self._regions:
                raise ValueError(f"CacheRegion '{name}' already exists")
            region = CacheRegion(
                name=name,
                max_entries=max_entries,
                max_bytes=max_bytes,
                size_fn=size_fn,
            )
            self._regions[name] = region
            return region

    def get_or_create_region(
        self,
        name: str,
        max_entries: int,
        max_bytes: int = 0,
        size_fn: Optional[SizeFn] = None,
    ) -> CacheRegion:
        """Return the existing region named ``name`` or create one."""
        with self._lock:
            if name in self._regions:
                return self._regions[name]
            return self.create_region(
                name=name,
                max_entries=max_entries,
                max_bytes=max_bytes,
                size_fn=size_fn,
            )

    def region(self, name: str) -> CacheRegion:
        """Return the region named ``name`` or raise KeyError."""
        with self._lock:
            if name not in self._regions:
                raise KeyError(f"CacheRegion '{name}' not found")
            return self._regions[name]

    def has_region(self, name: str) -> bool:
        with self._lock:
            return name in self._regions

    def remove_region(self, name: str) -> None:
        with self._lock:
            region = self._regions.pop(name, None)
            if region is not None:
                region.clear()

    def clear_all(self) -> None:
        with self._lock:
            for region in self._regions.values():
                region.clear()

    def names(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(self._regions.keys())

    def stats(self) -> Dict[str, RegionStats]:
        with self._lock:
            return {name: region.stats() for name, region in self._regions.items()}

    def total_bytes(self) -> int:
        with self._lock:
            return sum(r.stats().bytes for r in self._regions.values())

    def total_entries(self) -> int:
        with self._lock:
            return sum(len(r) for r in self._regions.values())


# ---------------------------------------------------------------------------
# Process-wide singleton (opt-in; callers may also build their own)
# ---------------------------------------------------------------------------


_GLOBAL_MANAGER: Optional[CacheManager] = None
_GLOBAL_LOCK = threading.RLock()


def get_global_cache_manager() -> CacheManager:
    """Return a process-wide ``CacheManager`` singleton."""
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is not None:
        return _GLOBAL_MANAGER
    with _GLOBAL_LOCK:
        if _GLOBAL_MANAGER is None:
            _GLOBAL_MANAGER = CacheManager()
    return _GLOBAL_MANAGER


def reset_global_cache_manager() -> None:
    """Drop the singleton; intended for tests only."""
    global _GLOBAL_MANAGER
    with _GLOBAL_LOCK:
        _GLOBAL_MANAGER = None


__all__ = [
    "CacheManager",
    "CacheRegion",
    "RegionStats",
    "SizeFn",
    "get_global_cache_manager",
    "reset_global_cache_manager",
]
