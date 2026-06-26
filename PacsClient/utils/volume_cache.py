"""Decoded-volume cache — pin/unpin, LRU eviction, and decode-COALESCING.

S4 of ``docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md``. **Pure stdlib +
threading** (no Qt / VTK / numpy at import). Introduced **UNUSED** in S4a so the contract is locked
+ unit-tested (incl. concurrency) before any wiring into the live decode path (S4b — a dedicated,
clinical-lane-validated commit). Zero runtime risk now.

What it closes
--------------
The architecture review found **C1**: ~5 viewer caches keyed by a bare ``series_number``, written
from worker threads with **no lock and no shared invalidation**, plus the same series decoding twice
(``load_single_series_by_number`` + ``load_series_preview`` + the ZetaBoost booster). This cache:

- is keyed by the **stable identity** ``(study_uid, series_uid)`` — multi-study number collisions
  are impossible;
- **coalesces decodes**: :meth:`get_or_create` runs the (expensive) factory **at most once** per key
  even under concurrent callers — the rest wait and share the result, so a series never decodes
  twice;
- **pins** the active viewport's volume so it is never evicted mid-view (``pin`` / ``unpin``);
- evicts **LRU** by entry count (and an optional byte budget), never a pinned entry;
- exposes **one invalidation bus** (:meth:`invalidate` / :meth:`invalidate_all`) a server-grew event
  uses, replacing the ad-hoc per-cache invalidations.

The factory runs OUTSIDE the cache lock, so a slow decode never blocks other keys.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

Key = Tuple[str, str]  # (study_uid, series_uid)


def make_key(study_uid: Any, series_uid: Any) -> Key:
    return (str(study_uid or "").strip(), str(series_uid or "").strip())


@dataclass
class _Entry:
    value: Any
    size: int = 0
    pinned: int = 0          # pin count (re-entrant); >0 = never evict
    last_used: float = field(default_factory=time.monotonic)


class VolumeCacheError(RuntimeError):
    """Raised to a waiter when the coalesced decode it was waiting on failed."""


class VolumeCache:
    """Thread-safe decoded-volume cache. All public methods are safe to call from any thread."""

    def __init__(self, max_entries: int = 8, max_bytes: int = 0) -> None:
        self._lock = threading.RLock()
        self._entries: Dict[Key, _Entry] = {}
        # key -> (Event, [result_holder]) for in-flight decodes (coalescing).
        self._inflight: Dict[Key, threading.Event] = {}
        self._inflight_error: Dict[Key, BaseException] = {}
        self._max_entries = max(1, int(max_entries))
        self._max_bytes = max(0, int(max_bytes))  # 0 = no byte budget
        self.hits = 0
        self.misses = 0
        self.coalesced = 0

    # -- configuration ----------------------------------------------------- #
    def set_max_entries(self, n: int) -> None:
        with self._lock:
            self._max_entries = max(1, int(n))
            self._evict_locked()

    # -- reads ------------------------------------------------------------- #
    def peek(self, key: Key) -> Optional[Any]:
        """Return the cached value without affecting LRU/coalescing, or None."""
        with self._lock:
            e = self._entries.get(key)
            return e.value if e is not None else None

    def __contains__(self, key: Key) -> bool:
        with self._lock:
            return key in self._entries

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"entries": len(self._entries), "inflight": len(self._inflight),
                    "hits": self.hits, "misses": self.misses, "coalesced": self.coalesced,
                    "pinned": sum(1 for e in self._entries.values() if e.pinned)}

    # -- the coalescing get-or-create -------------------------------------- #
    def get_or_create(self, key: Key, factory: Callable[[], Any], *, size: int = 0,
                      pin: bool = False) -> Any:
        """Return the cached value for ``key``; if absent, run ``factory()`` exactly once even
        under concurrent callers (the others wait and share the result). ``factory`` runs OUTSIDE
        the lock. Raises :class:`VolumeCacheError` to waiters if the owning decode failed."""
        with self._lock:
            e = self._entries.get(key)
            if e is not None:
                e.last_used = time.monotonic()
                if pin:
                    e.pinned += 1
                self.hits += 1
                return e.value
            ev = self._inflight.get(key)
            if ev is None:
                # We own the decode for this key.
                ev = threading.Event()
                self._inflight[key] = ev
                owner = True
            else:
                owner = False
                self.coalesced += 1

        if not owner:
            # Wait for the owner's decode, then return the now-cached value.
            ev.wait()
            with self._lock:
                err = self._inflight_error.pop(key, None)
                if err is not None and key not in self._entries:
                    raise VolumeCacheError(str(err))
                e = self._entries.get(key)
                if e is not None:
                    e.last_used = time.monotonic()
                    if pin:
                        e.pinned += 1
                    self.hits += 1
                    return e.value
            # Owner failed and left nothing — surface a miss-as-error.
            raise VolumeCacheError("coalesced decode produced no value for %r" % (key,))

        # Owner path: run the factory outside the lock.
        self.misses += 1
        try:
            value = factory()
        except BaseException as exc:  # noqa: BLE001 — propagate to waiters then re-raise
            with self._lock:
                self._inflight_error[key] = exc
                ev2 = self._inflight.pop(key, None)
            if ev2 is not None:
                ev2.set()
            raise
        with self._lock:
            self._entries[key] = _Entry(value=value, size=max(0, int(size)),
                                        pinned=1 if pin else 0)
            ev2 = self._inflight.pop(key, None)
            self._evict_locked()
        if ev2 is not None:
            ev2.set()
        return value

    def put(self, key: Key, value: Any, *, size: int = 0, pin: bool = False) -> None:
        with self._lock:
            self._entries[key] = _Entry(value=value, size=max(0, int(size)),
                                        pinned=1 if pin else 0)
            self._evict_locked()

    # -- pinning ----------------------------------------------------------- #
    def pin(self, key: Key) -> bool:
        with self._lock:
            e = self._entries.get(key)
            if e is None:
                return False
            e.pinned += 1
            return True

    def unpin(self, key: Key) -> bool:
        with self._lock:
            e = self._entries.get(key)
            if e is None or e.pinned <= 0:
                return False
            e.pinned -= 1
            return True

    def is_pinned(self, key: Key) -> bool:
        with self._lock:
            e = self._entries.get(key)
            return bool(e and e.pinned > 0)

    # -- invalidation bus -------------------------------------------------- #
    def invalidate(self, key: Key) -> bool:
        with self._lock:
            return self._entries.pop(key, None) is not None

    def invalidate_study(self, study_uid: Any) -> int:
        su = str(study_uid or "").strip()
        with self._lock:
            doomed = [k for k in self._entries if k[0] == su]
            for k in doomed:
                del self._entries[k]
            return len(doomed)

    def invalidate_all(self) -> int:
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            return n

    # -- internal ---------------------------------------------------------- #
    def _evict_locked(self) -> None:
        # Count cap: evict LRU non-pinned until within max_entries.
        def _over_count() -> bool:
            return len(self._entries) > self._max_entries

        def _over_bytes() -> bool:
            return self._max_bytes > 0 and sum(e.size for e in self._entries.values()) > self._max_bytes

        while _over_count() or _over_bytes():
            victim = None
            victim_lu = None
            for k, e in self._entries.items():
                if e.pinned > 0:
                    continue
                if victim is None or e.last_used < victim_lu:
                    victim, victim_lu = k, e.last_used
            if victim is None:
                break  # everything is pinned — cannot evict
            del self._entries[victim]
