from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque
from typing import Callable, Optional

from .disk_cache import ZetaBoostDiskCache

# ── Global download-activity flag ──────────────────────────────────────────
# True when ANY study is currently downloading system-wide.
# All ZetaBoost warmup workers check this; when True they use the same
# generous 2-second inter-series sleep used for the active-download case,
# preventing warmup ITK pipelines from competing with the downloader and UI.
# Updated by home_ui via set_global_download_active() on download start/end.
_GLOBAL_DOWNLOAD_ACTIVE: bool = False


def set_global_download_active(active: bool) -> None:
    """Set whether ANY study is currently downloading system-wide.

    When True, ALL ZetaBoost warmup workers throttle to a 2-second
    inter-series sleep, keeping CPU and GIL free for the viewer and
    download thread even when the download is for a different patient.
    """
    global _GLOBAL_DOWNLOAD_ACTIVE
    _GLOBAL_DOWNLOAD_ACTIVE = bool(active)


def _set_thread_low_priority():
    """Lower current thread's OS scheduling priority.

    On Windows: THREAD_PRIORITY_IDLE (-15) via Win32 API.
    This is the LOWEST non-realtime priority, ensuring warmup/background
    threads never starve the UI or download threads for CPU time.
    On Linux: nice +15 via os.nice().
    Silently no-ops on failure so it never breaks the worker.
    """
    try:
        if sys.platform == 'win32':
            import ctypes
            # SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_IDLE=-15)
            handle = ctypes.windll.kernel32.GetCurrentThread()
            ctypes.windll.kernel32.SetThreadPriority(handle, -15)
        else:
            os.nice(15)
    except Exception:
        pass


class ZetaBoostEngine:
    """Active-tab-only cache + serialized preloading/processing engine.

    Each PatientWidget/ViewerController owns one engine instance.
    Engine is active only while its tab is the currently viewed tab.
    """

    # ── Change #7: Global download counter (class-level, shared across ALL instances) ──
    # Tracks how many study downloads are currently active in the whole application.
    # When this counter is > 0, ALL engine instances block warmup/background lanes,
    # preventing cross-study ITK CPU saturation (Root Cause #2 in Mode B analysis).
    _global_active_download_count: int = 0
    _global_download_lock: "threading.Lock" = None  # lazily initialised below

    @classmethod
    def _get_global_lock(cls):
        """Return (and lazily create) the class-level global download lock."""
        if cls._global_download_lock is None:
            import threading as _threading
            cls._global_download_lock = _threading.Lock()
        return cls._global_download_lock

    @classmethod
    def notify_global_download_start(cls) -> None:
        """
        Call when ANY study download begins anywhere in the application.
        Blocks warmup/background lanes on ALL engine instances immediately.
        """
        with cls._get_global_lock():
            cls._global_active_download_count += 1
        import logging as _logging
        _logging.getLogger(__name__).info(
            f"[ZetaBoost][Global] Download started. "
            f"Active downloads: {cls._global_active_download_count}",
            extra={"component": "zetaboost"},
        )

    @classmethod
    def notify_global_download_stop(cls) -> None:
        """
        Call when ANY study download completes or is cancelled.
        Unblocks warmup/background lanes when no more downloads are active.
        """
        with cls._get_global_lock():
            cls._global_active_download_count = max(0, cls._global_active_download_count - 1)
        import logging as _logging
        _logging.getLogger(__name__).info(
            f"[ZetaBoost][Global] Download stopped. "
            f"Active downloads: {cls._global_active_download_count}",
            extra={"component": "zetaboost"},
        )

    def __init__(
        self,
        *,
        tab_key: str,
        estimate_bytes_fn: Callable[[object], int],
        load_series_callback: Callable[[str], None],
        max_entries: int = 24,
        byte_budget: int = 1200 * 1024 * 1024,
        max_parallel_loads: int = 2,
        warmup_workers: int = 2,
        background_workers: int = 2,
        enable_disk_cache: bool = True,
        disk_cache_max_bytes: int = 20 * 1024 * 1024 * 1024,
        disk_cache_max_entries: int = 600,
        disk_persist_max_bytes: int = 260 * 1024 * 1024,
        logger=None,
    ):
        self.tab_key = str(tab_key or "unknown")
        self._estimate_bytes_fn = estimate_bytes_fn
        self._load_series_callback = load_series_callback
        self._max_entries = max(1, int(max_entries))
        self._byte_budget = max(1, int(byte_budget))
        self._max_parallel_loads = max(1, int(max_parallel_loads or 1))
        self._warmup_workers = max(1, min(6, int(warmup_workers or 2)))
        self._background_workers = max(1, min(4, int(background_workers or 2)))
        self._disk_persist_max_bytes = max(1, int(disk_persist_max_bytes or 1))
        self._logger = logger

        self._active = False

        self._cache = {}  # series_number -> (vtk_image_data, metadata, est_bytes)
        self._cache_order = []
        self._cache_bytes = 0
        self._protected_series = set()  # actively displayed series; evict last

        self._lane_order = ("interactive", "warmup", "background")
        self._lane_rank = {"interactive": 0, "warmup": 1, "background": 2}
        self._queue = {lane: deque() for lane in self._lane_order}
        self._queued = {lane: set() for lane in self._lane_order}
        self._inflight = {lane: set() for lane in self._lane_order}
        self._queued_lane_map = {}  # series_number -> lane

        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._worker_threads = {lane: [] for lane in self._lane_order}
        self._external_interactive_busy = False
        self._download_active = False  # True while Zeta download is running
        self._study_download_complete = True  # Definitive flag from PipelineOrchestrator
        # Mode B: when True, put() is a no-op — ImageSliceBooster handles
        # the active series and no series-level data enters the 1.2 GB RAM pool.
        self._image_boost_mode: bool = False

        self._stats = {
            "mem_hit": 0,
            "disk_hit": 0,
            "miss": 0,
            "put": 0,
            "queued": 0,
            "processed": 0,
            "failed": 0,
        }
        self._consecutive_failures = 0
        self._max_consecutive_failures = 8
        self._last_health_log_ts = 0.0
        # Keep telemetry cheap by default; still explicit enough for diagnostics.
        self._health_log_interval_sec = 30.0

        # Performance guard: avoid repeated disk-cache probes for known short-term misses.
        self._recent_disk_miss = {}  # series_number -> ts
        self._recent_disk_miss_ttl_sec = 8.0

        self._disk_cache = None
        if bool(enable_disk_cache):
            try:
                self._disk_cache = ZetaBoostDiskCache(
                    max_bytes=int(disk_cache_max_bytes),
                    max_entries=int(disk_cache_max_entries),
                    logger=self._logger,
                )
            except Exception:
                self._disk_cache = None

    # ------------------------- logging -------------------------
    def _log_info(self, message: str):
        msg = f"[ZetaBoost] {message}"
        try:
            # Always print to terminal for runtime verification.
            print(msg)
        except Exception:
            pass
        try:
            if self._logger is not None:
                self._logger.info(msg)
        except Exception:
            pass

    def _cache_summary(self) -> str:
        mb = self._cache_bytes / (1024 * 1024)
        budget_mb = self._byte_budget / (1024 * 1024)
        q_interactive = len(self._queue["interactive"])
        q_warmup = len(self._queue["warmup"])
        q_background = len(self._queue["background"])
        i_interactive = len(self._inflight["interactive"])
        i_warmup = len(self._inflight["warmup"])
        i_background = len(self._inflight["background"])
        return (
            f"tab={self.tab_key} "
            f"entries={len(self._cache_order)} "
            f"bytes={mb:.1f}MB/{budget_mb:.1f}MB "
            f"queued={q_interactive + q_warmup + q_background} "
            f"inflight={i_interactive + i_warmup + i_background} "
            f"q(i/w/b)={q_interactive}/{q_warmup}/{q_background} "
            f"in(i/w/b)={i_interactive}/{i_warmup}/{i_background}"
        )

    def _stats_summary(self) -> str:
        s = self._stats
        return (
            f"hits(mem/disk)={s['mem_hit']}/{s['disk_hit']} "
            f"miss={s['miss']} put={s['put']} queued={s['queued']} "
            f"processed={s['processed']} failed={s['failed']}"
        )

    def _maybe_log_health_locked(self, force: bool = False):
        now = time.time()
        if force or (now - float(self._last_health_log_ts or 0.0) >= self._health_log_interval_sec):
            self._last_health_log_ts = now
            self._log_info(f"HEALTH {self._cache_summary()} {self._stats_summary()}")

    def _is_recent_disk_miss_locked(self, key: str) -> bool:
        ts = self._recent_disk_miss.get(key)
        if ts is None:
            return False
        if (time.time() - float(ts)) <= self._recent_disk_miss_ttl_sec:
            return True
        self._recent_disk_miss.pop(key, None)
        return False

    # ------------------------- lifecycle -------------------------
    def activate(self):
        with self._cv:
            if self._active:
                return
            self._active = True
            self._stop_event.clear()
            self._ensure_workers_locked()
            self._cv.notify_all()
            self._log_info(f"ACTIVE {self._cache_summary()}")
            self._maybe_log_health_locked(force=True)

    def deactivate(self, clear_cache: bool = True):
        with self._cv:
            if (not self._active) and (not clear_cache):
                return
            self._active = False
            self._stop_event.set()
            for lane in self._lane_order:
                self._queue[lane].clear()
                self._queued[lane].clear()
                self._inflight[lane].clear()
            self._queued_lane_map.clear()
            self._protected_series.clear()
            if clear_cache:
                self._clear_cache_locked()
            self._cv.notify_all()
            self._log_info(f"INACTIVE clear_cache={clear_cache} {self._cache_summary()}")
            self._maybe_log_health_locked(force=True)

    def is_active(self) -> bool:
        with self._lock:
            return bool(self._active)

    def has_lane_activity(self, lane: str = "background") -> bool:
        """Return True when the given lane currently has queued or inflight work."""
        ln = self._normalize_lane(lane)
        with self._lock:
            return bool(self._queue[ln] or self._inflight[ln])

    def get_capacity_snapshot(self) -> dict:
        """Return lightweight cache capacity state for admission policies."""
        with self._lock:
            return {
                "entries": int(len(self._cache_order)),
                "bytes": int(self._cache_bytes),
                "byte_budget": int(self._byte_budget),
                "max_entries": int(self._max_entries),
            }

    def has_in_memory(self, series_number: str) -> bool:
        """Non-mutating cache membership check (memory cache only).

        Important: unlike get(), this does NOT trigger disk-cache reads, put(),
        eviction, or stats mutations. Safe for high-frequency filter paths.
        """
        key = str(series_number)
        if not key:
            return False
        with self._lock:
            return key in self._cache

    def has_any_cache_non_mutating(self, series_number: str) -> bool:
        """Return True if series is cached in memory OR disk manifest.

        No payload deserialize, no put/evict, no stats mutation.
        """
        key = str(series_number)
        if not key:
            return False
        with self._lock:
            if key in self._cache:
                return True
        try:
            if self._disk_cache is not None:
                return bool(self._disk_cache.has(self.tab_key, key))
        except Exception:
            pass
        return False

    def set_external_interactive_busy(self, busy: bool):
        """Hint from controller: an external interactive load is running.

        While true, warmup/background workers are paused to avoid I/O/CPU contention
        with user-triggered drag/drop loads.
        """
        with self._cv:
            self._external_interactive_busy = bool(busy)
            self._cv.notify_all()

    def wait_for_inflight_drain(self, timeout_sec: float = 3.0) -> bool:
        """Wait until no inflight loads remain in any lane.

        Called by the interactive switch worker before starting its own ITK pipeline
        so the two pipelines do not compete for CPU on weak hardware (e.g. GLES2/PC B).
        Running alone is faster (1.7-4s) than competing concurrently (3-6s).

        Returns True if all inflight work drained within the timeout, False otherwise.
        """
        deadline = time.time() + float(timeout_sec)
        with self._cv:
            while self._total_inflight_locked() > 0:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return False
                self._cv.wait(timeout=min(remaining, 0.25))
        return True

    def set_download_active(self, active: bool):
        """Legacy signal that a Zeta download is in progress.

        Kept for backward compatibility.  The definitive gating is now
        handled by ``set_study_download_complete()`` which is driven by
        the PipelineOrchestrator's study-level download signal.
        """
        with self._cv:
            was = self._download_active
            self._download_active = bool(active)
            if was != self._download_active:
                self._log_info(f"DOWNLOAD_ACTIVE={self._download_active} {self._cache_summary()}")
            self._cv.notify_all()

    def set_study_download_complete(self, complete: bool):
        """Definitive signal from PipelineOrchestrator.

        While *complete* is False, warmup/background lanes are BLOCKED.
        While True, they may proceed (subject to other gating).
        This replaces the old timer-based ``set_download_active`` heuristic
        with a deterministic study-level signal.
        """
        with self._cv:
            was = self._study_download_complete
            self._study_download_complete = bool(complete)
            if was != self._study_download_complete:
                self._log_info(
                    f"STUDY_DOWNLOAD_COMPLETE={self._study_download_complete} "
                    f"{self._cache_summary()}"
                )
            self._cv.notify_all()

    def set_image_boost_mode(self, active: bool) -> None:
        """Enable / disable Image Boost Mode (Mode B).

        When *active* is True:
        - ``put()`` is a no-op — series-level data does NOT enter the RAM pool.
        - warmup/background lanes are already blocked (``_study_download_complete``
          is False during Mode B), so no extra gate is needed here.
        - Interactive lane still delivers data to the viewer but bypasses the cache.

        The ViewerController calls this from ``_on_pipeline_state_changed``:
        - ``DOWNLOADING``    → ``set_image_boost_mode(True)``
        - ``POST_DOWNLOAD``  → ``set_image_boost_mode(False)``
        """
        with self._cv:
            was = self._image_boost_mode
            self._image_boost_mode = bool(active)
            if was != self._image_boost_mode:
                self._log_info(
                    f"IMAGE_BOOST_MODE={self._image_boost_mode} "
                    f"{self._cache_summary()}"
                )
            self._cv.notify_all()

    @property
    def is_image_boost_mode(self) -> bool:
        """True during Mode B (image-level boost only; series cache disabled)."""
        with self._lock:
            return bool(self._image_boost_mode)

    def clear_all(self):
        self.deactivate(clear_cache=True)
        try:
            if self._disk_cache is not None:
                self._disk_cache.clear_tab(self.tab_key)
        except Exception:
            pass
        with self._lock:
            self._consecutive_failures = 0
            self._recent_disk_miss.clear()

    def set_protected_series(self, series_numbers):
        """Update series numbers that should be evicted last.

        Typical usage: protect currently displayed series in active viewers so
        interactive drag/drop remains cache-hot under memory pressure.
        """
        try:
            new_set = {str(sn) for sn in (series_numbers or []) if str(sn)}
        except Exception:
            new_set = set()
        with self._cv:
            if new_set == self._protected_series:
                return
            self._protected_series = new_set
            self._cv.notify_all()

    # ------------------------- cache -------------------------
    def query(self, series_number: str):
        """Instant, non-blocking cache probe.  Returns (vtk, meta, bytes) or None.

        This is the PRIMARY viewer-facing API.  The viewer asks ZetaBoost:
        "Do you have this series ready?"  The answer is always instant (O(1) dict lookup).
        If None → ZetaBoost is "not ready" → viewer proceeds with its own normal loading.

        Never touches disk cache, never blocks, never allocates.
        """
        key = str(series_number)
        with self._lock:
            val = self._cache.get(key)
            if val is not None:
                try:
                    if key in self._cache_order:
                        self._cache_order.remove(key)
                    self._cache_order.append(key)
                except Exception:
                    pass
                self._stats["mem_hit"] += 1
                return val
            self._stats["miss"] += 1
        return None

    def get(self, series_number: str, memory_only: bool = False):
        """Retrieve cached series data.

        For external callers: prefer query() which is always instant.
        get() with memory_only=False is used internally by engine workers
        to promote disk→memory.  External callers should ALWAYS use
        memory_only=True (or just call query()).

        Args:
            series_number: The series identifier.
            memory_only: When True, only check the in-memory cache.
                Skip disk-cache deserialization entirely.
        """
        key = str(series_number)
        with self._lock:
            val = self._cache.get(key)
            if val is None:
                pass
            else:
                try:
                    if key in self._cache_order:
                        self._cache_order.remove(key)
                    self._cache_order.append(key)
                except Exception:
                    pass
                self._stats["mem_hit"] += 1
                self._maybe_log_health_locked(force=False)
                return val

        # In memory_only mode stop here.  This keeps UI-thread callers
        # non-blocking (disk deserialization can take seconds for large
        # series and MUST NOT run on the Qt event loop).
        if memory_only:
            with self._lock:
                self._stats["miss"] += 1
                self._maybe_log_health_locked(force=False)
            return None

        if self._disk_cache is not None:
            with self._lock:
                if self._is_recent_disk_miss_locked(key):
                    self._stats["miss"] += 1
                    self._maybe_log_health_locked(force=False)
                    return None
            try:
                payload = self._disk_cache.get(self.tab_key, key)
                if payload is not None:
                    vtk_image_data, metadata = payload
                    self.put(key, vtk_image_data, metadata, persist_disk=False)
                    with self._lock:
                        self._stats["disk_hit"] += 1
                        self._recent_disk_miss.pop(key, None)
                        self._maybe_log_health_locked(force=False)
                    self._log_info(f"DISK_HIT series={key} {self._cache_summary()}")
                    with self._lock:
                        return self._cache.get(key)
                else:
                    with self._lock:
                        self._recent_disk_miss[key] = time.time()
            except Exception:
                with self._lock:
                    self._recent_disk_miss[key] = time.time()

        with self._lock:
            self._stats["miss"] += 1
            self._maybe_log_health_locked(force=False)

        return None

    def put(self, series_number: str, vtk_image_data, metadata, persist_disk: bool = True, promote_immediately: bool = False, force_during_download: bool = False):
        """
        Put series into cache with optional immediate promotion.

        In Image Boost Mode (Mode B) this method is a deliberate no-op:
        the full-series VTK volume must NOT enter the 1.2 GB RAM pool while a
        3 000-image study is downloading concurrently.  The viewer keeps its own
        reference to the loaded ``vtkImageData``; ZetaBoost caching is resumed
        automatically when the download completes (POST_DOWNLOAD transition).

        When ``force_during_download=True`` the Mode B guard is bypassed.
        This is used by the controlled per-series download warmup path which
        caches a small number of already-completed series while the study
        download is still in progress.  The caller is responsible for
        enforcing RAM / concurrency limits.

        Args:
            series_number: Series identifier
            vtk_image_data: VTK image data
            metadata: Series metadata
            persist_disk: Whether to persist to disk cache (default True)
            promote_immediately: If True, prioritize memory over disk write latency
                                 (used during user-initiated drag & drop)
            force_during_download: If True, bypass Mode B guard (used by
                                   per-series download warmup only)
        """
        # Mode B guard: skip series-level caching to bound RAM footprint.
        # Bypassed when force_during_download=True (controlled per-series warmup).
        with self._lock:
            _ibm = self._image_boost_mode
        if _ibm and not force_during_download:
            self._log_info(
                f"PUT_SKIPPED_IMAGE_BOOST series={series_number} (Mode B active)"
            )
            return
        key = str(series_number)
        est_bytes = 0
        try:
            est_bytes = int(self._estimate_bytes_fn(vtk_image_data) or 0)
        except Exception:
            est_bytes = 0

        with self._lock:
            if key in self._cache:
                try:
                    _ovtk, _ometa, obytes = self._cache[key]
                    self._cache_bytes = max(0, self._cache_bytes - int(obytes or 0))
                except Exception:
                    pass
                try:
                    if key in self._cache_order:
                        self._cache_order.remove(key)
                except Exception:
                    pass

            self._cache[key] = (vtk_image_data, metadata, est_bytes)
            self._cache_order.append(key)
            self._cache_bytes += est_bytes

            self._evict_locked()
            self._stats["put"] += 1
            self._log_info(f"CACHED series={key} {self._cache_summary()}")
            self._maybe_log_health_locked(force=False)

        # ✅ OPTIMIZATION: Aggressive disk persistence for better next-load performance
        if persist_disk and self._disk_cache is not None:
            # معیار: برای interactive lane (user drag & drop)، بیشتر series ها را persist کن
            persist_threshold = self._disk_persist_max_bytes * 1.5 if promote_immediately else self._disk_persist_max_bytes
            
            if est_bytes <= persist_threshold:
                # Offload np.savez_compressed + SQLite write to a daemon thread so
                # callers (especially the Qt UI thread during priming) are never
                # blocked by heavy I/O.  The in-memory cache was already updated
                # synchronously above, so reads are served immediately.
                _dc = self._disk_cache
                _tk = self.tab_key
                _lk = self._lock
                _rdm = self._recent_disk_miss
                _log = self._log_info

                def _async_disk_write():
                    try:
                        _dc.put(_tk, key, vtk_image_data, metadata)
                        with _lk:
                            _rdm.pop(key, None)
                    except Exception as _exc:
                        _log(f"DISK_WRITE_ERR series={key} error={_exc}")

                # ✅ OPTIMIZATION: اگر promote_immediately، disk write را بیس‌تر اولویت دهید
                threading.Thread(
                    target=_async_disk_write,
                    daemon=True,
                    name=f"ZB-DiskW-{key[:20]}",
                    priority=-1 if promote_immediately else None,  # Higher priority for drag & drop
                ).start()
            else:
                self._log_info(
                    f"DISK_SKIP_LARGE series={key} est_bytes={est_bytes} threshold={persist_threshold}"
                )

    def trim_keep(self, keep_entries: int):
        keep_entries = max(0, int(keep_entries))
        with self._lock:
            removed = 0
            while len(self._cache_order) > keep_entries:
                old = self._cache_order.pop(0)
                if old in self._cache:
                    try:
                        _rvtk, _rmeta, rbytes = self._cache[old]
                        self._cache_bytes = max(0, self._cache_bytes - int(rbytes or 0))
                    except Exception:
                        pass
                    del self._cache[old]
                    removed += 1
            if removed:
                self._log_info(f"TRIM keep={keep_entries} removed={removed} {self._cache_summary()}")

    # ------------------------- queue -------------------------
    def _normalize_lane(self, lane: Optional[str]) -> str:
        candidate = str(lane or "interactive").strip().lower()
        if candidate not in self._lane_rank:
            return "interactive"
        return candidate

    def _remove_from_lane_queue_locked(self, key: str, lane: str):
        dq = self._queue[lane]
        if not dq:
            return
        self._queue[lane] = deque(x for x in dq if x != key)

    def _is_inflight_locked(self, key: str) -> bool:
        for lane in self._lane_order:
            if key in self._inflight[lane]:
                return True
        return False

    def _total_inflight_locked(self) -> int:
        return sum(len(self._inflight[lane]) for lane in self._lane_order)

    def _can_start_lane_locked(self, lane: str) -> bool:
        # ── Change #7: Block warmup/background if ANY download is active globally ──
        # Using class-level counter ensures that Patient A's engine is blocked
        # when Patient B's study is downloading (cross-study ITK saturation fix).
        if (ZetaBoostEngine._global_active_download_count > 0
                and lane in ("warmup", "background")):
            return False

        if self._total_inflight_locked() >= self._max_parallel_loads:
            return False
        # While a Zeta download is running, block ALL lanes — including
        # interactive — to prevent CPU/GIL contention with the viewer.
        # The viewer will fall back to direct DICOM loading for any series
        # not yet in the ZetaBoost in-memory cache.
        # (Mode B: _download_active is False, so nothing is blocked here.)
        if self._download_active:
            return False
        if lane == "interactive":
            return True
        if self._external_interactive_busy:
            return False
        # Additional guard: only allow 1 inflight for non-interactive lanes
        # to prevent multiple concurrent ITK loads from starving the UI.
        if lane != "interactive" and self._total_inflight_locked() >= 1:
            return False
        # Definitive download gate (PipelineOrchestrator → set_study_download_complete).
        # Warmup/background lanes are NEVER allowed until the study download
        # is definitively complete.  This replaces the old timer-based
        # heuristic that could misfire between closely-spaced downloads.
        if not self._study_download_complete and lane in ("warmup", "background"):
            return False
        # Legacy timer-based fallback (kept for safety).
        if self._download_active and lane in ("warmup", "background"):
            return False
        if lane == "warmup":
            # Don't start warmup while an interactive task is waiting.
            return len(self._queue["interactive"]) == 0
        # background: only when higher-priority lanes are empty.
        return len(self._queue["interactive"]) == 0 and len(self._queue["warmup"]) == 0

    def _wait_reason_locked(self, lane: str) -> str:
        """Diagnostic: why is this lane blocked right now?"""
        reasons = []
        # Change #7: global download gate
        if (ZetaBoostEngine._global_active_download_count > 0
                and lane in ("warmup", "background")):
            reasons.append(
                f"global_download_active({ZetaBoostEngine._global_active_download_count})"
            )
        if not self._active:
            reasons.append("engine_inactive")
        if not self._queue[lane]:
            reasons.append("queue_empty")
        if self._total_inflight_locked() >= self._max_parallel_loads:
            reasons.append(f"max_parallel({self._total_inflight_locked()}/{self._max_parallel_loads})")
        if self._external_interactive_busy and lane != "interactive":
            reasons.append("interactive_busy")
        if not self._study_download_complete and lane != "interactive":
            reasons.append("study_download_pending")
        if self._download_active:
            # All lanes blocked while download is running (including interactive)
            reasons.append("download_active(all_lanes)")
        if lane == "warmup" and len(self._queue.get("interactive", [])):
            reasons.append("interactive_queued")
        if lane == "background":
            if len(self._queue.get("interactive", [])):
                reasons.append("interactive_queued")
            if len(self._queue.get("warmup", [])):
                reasons.append("warmup_queued")
        return ",".join(reasons) if reasons else "ready"

    def enqueue(self, series_number: str, lane: str = "interactive"):
        key = str(series_number)
        if not key:
            return
        lane = self._normalize_lane(lane)
        with self._cv:
            if not self._active:
                return
            if key in self._cache:
                return
            if self._is_inflight_locked(key):
                return

            existing_lane = self._queued_lane_map.get(key)
            if existing_lane == lane:
                return

            promoted = False
            if existing_lane is not None:
                if self._lane_rank[lane] < self._lane_rank[existing_lane]:
                    self._remove_from_lane_queue_locked(key, existing_lane)
                    self._queued[existing_lane].discard(key)
                    promoted = True
                else:
                    return

            self._queue[lane].append(key)
            self._queued[lane].add(key)
            self._queued_lane_map[key] = lane
            self._stats["queued"] += 1
            self._ensure_workers_locked()
            self._cv.notify_all()
            if promoted:
                self._log_info(f"QUEUED_PROMOTE series={key} lane={lane} {self._cache_summary()}")
            else:
                self._log_info(f"QUEUED series={key} lane={lane} {self._cache_summary()}")

    def enqueue_many(self, series_numbers, lane: str = "warmup"):
        lane = self._normalize_lane(lane)
        with self._cv:
            if not self._active:
                return
            added = 0
            promoted = 0
            skipped = 0
            for sn in series_numbers or []:
                key = str(sn)
                if not key:
                    skipped += 1
                    continue
                if key in self._cache:
                    skipped += 1
                    continue
                if self._is_inflight_locked(key):
                    skipped += 1
                    continue

                existing_lane = self._queued_lane_map.get(key)
                if existing_lane == lane:
                    skipped += 1
                    continue

                if existing_lane is not None:
                    if self._lane_rank[lane] < self._lane_rank[existing_lane]:
                        self._remove_from_lane_queue_locked(key, existing_lane)
                        self._queued[existing_lane].discard(key)
                        self._queue[lane].append(key)
                        self._queued[lane].add(key)
                        self._queued_lane_map[key] = lane
                        promoted += 1
                    else:
                        skipped += 1
                    continue

                self._queue[lane].append(key)
                self._queued[lane].add(key)
                self._queued_lane_map[key] = lane
                added += 1
                self._stats["queued"] += 1
            self._ensure_workers_locked()
            self._cv.notify_all()
            if added or promoted:
                self._log_info(
                    f"QUEUED_BATCH lane={lane} added={added} promoted={promoted} skipped={skipped} "
                    f"{self._cache_summary()}"
                )
                self._maybe_log_health_locked(force=False)

    def enqueue_interactive(self, series_number: str):
        self.enqueue(series_number, lane="interactive")

    def enqueue_warmup(self, series_number: str):
        self.enqueue(series_number, lane="warmup")

    def enqueue_background(self, series_number: str):
        self.enqueue(series_number, lane="background")

    def enqueue_many_warmup(self, series_numbers):
        self.enqueue_many(series_numbers, lane="warmup")

    def enqueue_many_background(self, series_numbers):
        self.enqueue_many(series_numbers, lane="background")

    def clear_pending(self):
        with self._cv:
            old_q = sum(len(self._queue[lane]) for lane in self._lane_order)
            for lane in self._lane_order:
                self._queue[lane].clear()
                self._queued[lane].clear()
            self._queued_lane_map.clear()
            self._recent_disk_miss.clear()
            self._cv.notify_all()
            if old_q:
                self._log_info(f"CLEAR_PENDING removed={old_q} {self._cache_summary()}")

    def _remove_from_mem_cache_locked(self, key: str):
        if key not in self._cache:
            return False
        try:
            _rvtk, _rmeta, rbytes = self._cache[key]
            self._cache_bytes = max(0, self._cache_bytes - int(rbytes or 0))
        except Exception:
            pass
        try:
            if key in self._cache_order:
                self._cache_order.remove(key)
        except Exception:
            pass
        del self._cache[key]
        return True

    def invalidate_series(self, series_number: str, clear_disk: bool = True):
        """Purge all runtime traces of one series to avoid cumulative corruption."""
        key = str(series_number)
        removed_mem = False
        removed_q = 0
        with self._cv:
            removed_mem = self._remove_from_mem_cache_locked(key)
            for lane in self._lane_order:
                before = len(self._queue[lane])
                self._remove_from_lane_queue_locked(key, lane)
                after = len(self._queue[lane])
                removed_q += max(0, before - after)
                self._queued[lane].discard(key)
                self._inflight[lane].discard(key)
            self._queued_lane_map.pop(key, None)
            self._recent_disk_miss.pop(key, None)
            self._cv.notify_all()

        removed_disk = False
        if clear_disk and self._disk_cache is not None:
            try:
                self._disk_cache.delete_entry(self.tab_key, key)
                removed_disk = True
            except Exception:
                pass

        self._log_info(
            f"INVALIDATE series={key} removed_mem={removed_mem} removed_queue={removed_q} removed_disk={removed_disk} "
            f"{self._cache_summary()}"
        )

    def _failsafe_reset_locked(self, reason: str):
        pending = sum(len(self._queue[lane]) for lane in self._lane_order)
        for lane in self._lane_order:
            self._queue[lane].clear()
            self._queued[lane].clear()
            self._inflight[lane].clear()
        self._queued_lane_map.clear()
        self._recent_disk_miss.clear()
        self._clear_cache_locked()
        self._consecutive_failures = 0
        self._log_info(f"FAILSAFE_RESET reason={reason} pending_cleared={pending} {self._cache_summary()}")

    def _failsafe_reset(self, reason: str):
        with self._cv:
            self._failsafe_reset_locked(reason)
            self._cv.notify_all()
        if self._disk_cache is not None:
            try:
                self._disk_cache.clear_tab(self.tab_key)
            except Exception:
                pass

    # ------------------------- internals -------------------------
    def _ensure_workers_locked(self):
        for lane in self._lane_order:
            threads = self._worker_threads.get(lane, [])
            alive = [t for t in threads if t.is_alive()]
            self._worker_threads[lane] = alive
            # Interactive: 1 (serialized user actions).
            # Warmup/background: configurable (scales with system RAM).
            if lane == "interactive":
                required = 1
            elif lane == "warmup":
                required = self._warmup_workers
            else:
                required = self._background_workers
            if len(alive) >= required:
                continue
            for idx in range(len(alive), required):
                th = threading.Thread(
                    target=self._worker_loop,
                    args=(lane, idx),
                    daemon=True,
                    name=f"ZetaBoost-{self.tab_key[:16]}-{lane[:4]}-{idx + 1}",
                )
                th.start()
                self._worker_threads[lane].append(th)

    def _try_promote_disk_to_memory(self, series_number: str) -> bool:
        """Attempt disk→memory promotion directly inside the engine.

        Returns True if the series was loaded from disk cache into memory
        without needing the user callback.  This avoids the costly
        callback → engine.get() round-trip that doubled latency.
        """
        key = str(series_number)
        with self._lock:
            if key in self._cache:
                return True  # already in memory
            if self._is_recent_disk_miss_locked(key):
                return False
        if self._disk_cache is None:
            return False
        try:
            _t = time.time()
            payload = self._disk_cache.get(self.tab_key, key)
            _elapsed_ms = (time.time() - _t) * 1000
            if payload is not None:
                vtk_image_data, metadata = payload
                self.put(key, vtk_image_data, metadata, persist_disk=False)
                with self._lock:
                    self._stats["disk_hit"] += 1
                    self._recent_disk_miss.pop(key, None)
                self._log_info(f"DISK_PROMOTE series={key} {_elapsed_ms:.0f}ms {self._cache_summary()}")
                return True
            else:
                with self._lock:
                    self._recent_disk_miss[key] = time.time()
        except Exception:
            with self._lock:
                self._recent_disk_miss[key] = time.time()
        return False

    # ── System RAM guard for workers ──
    _RAM_CHECK_INTERVAL_SEC = 3.0  # don't call psutil every iteration
    _RAM_MIN_AVAIL_MB = 1200       # pause warmup/background if below this (raised from 800)

    def _check_system_memory_ok(self, lane: str) -> bool:
        """Return False if system RAM is too low for non-interactive work.

        Interactive lane always proceeds (never block the user).
        Warmup/background lanes pause when the OS is under memory pressure
        so ZetaBoost never degrades the main workflow.
        """
        if lane == "interactive":
            return True
        now = time.time()
        if (now - getattr(self, '_last_ram_check_ts', 0.0)) < self._RAM_CHECK_INTERVAL_SEC:
            return getattr(self, '_last_ram_ok', True)
        try:
            import psutil
            avail_mb = int(psutil.virtual_memory().available / (1024 * 1024))
            ok = avail_mb >= self._RAM_MIN_AVAIL_MB
            self._last_ram_check_ts = now
            self._last_ram_ok = ok
            if not ok:
                self._log_info(
                    f"RAM_PRESSURE lane={lane} available={avail_mb}MB < min={self._RAM_MIN_AVAIL_MB}MB → pausing"
                )
            return ok
        except Exception:
            self._last_ram_check_ts = now
            self._last_ram_ok = True
            return True

    def _worker_loop(self, lane: str, worker_index: int):
        # Lower OS thread priority so worker threads never starve
        # the UI/rendering thread or download threads.
        _set_thread_low_priority()
        _last_block_log = 0.0
        while True:
            with self._cv:
                while (
                    (not self._active)
                    or (not self._queue[lane])
                    or (not self._can_start_lane_locked(lane))
                    or (not self._check_system_memory_ok(lane))
                ) and not self._stop_event.is_set():
                    # Log blocking reason periodically (every 5s)
                    _now = time.time()
                    if _now - _last_block_log >= 5.0 and self._active and self._queue[lane]:
                        _reason = self._wait_reason_locked(lane)
                        if not getattr(self, '_last_ram_ok', True):
                            _reason += ",low_ram"
                        self._log_info(
                            f"WORKER_BLOCKED lane={lane} worker={worker_index+1} "
                            f"reason={_reason} pending={len(self._queue[lane])} {self._cache_summary()}"
                        )
                        _last_block_log = _now
                    self._cv.wait(timeout=2.0)

                if self._stop_event.is_set() and (
                    (not self._active)
                    or all(len(self._queue[l]) == 0 for l in self._lane_order)
                ):
                    return

                if not self._active:
                    continue

                series_number = self._queue[lane].popleft() if self._queue[lane] else None
                if not series_number:
                    continue

                self._queued[lane].discard(series_number)
                self._queued_lane_map.pop(series_number, None)
                self._inflight[lane].add(series_number)

            self._log_info(
                f"PROCESS_START lane={lane} worker={worker_index + 1} "
                f"series={series_number} {self._cache_summary()}"
            )

            failed = False
            try:
                # Fast path: if the series exists in the disk cache, promote it
                # directly to memory without calling the user callback.
                # This avoids DICOM+ITK loading and the callback→engine.get()
                # round-trip that previously doubled disk-read latency.
                if self._try_promote_disk_to_memory(series_number):
                    # Successfully loaded from disk — no callback needed.
                    pass
                else:
                    ret = self._load_series_callback(str(series_number))
                    if isinstance(ret, bool) and (ret is False):
                        failed = True
            except Exception as e:
                failed = True
                if self._logger:
                    try:
                        self._logger.debug(f"ZetaBoost load failed for series {series_number}: {e}")
                    except Exception:
                        pass
            finally:
                with self._cv:
                    self._inflight[lane].discard(series_number)
                    self._stats["processed"] += 1
                    if failed:
                        self._stats["failed"] += 1
                        self._consecutive_failures += 1
                    else:
                        self._consecutive_failures = 0
                    self._log_info(
                        f"PROCESS_DONE lane={lane} worker={worker_index + 1} "
                        f"series={series_number} {self._cache_summary()}"
                    )
                    self._maybe_log_health_locked(force=False)
                    # Detect when ALL work across all lanes is complete.
                    _all_done = self._active and all(
                        len(self._queue[l]) == 0 and len(self._inflight[l]) == 0
                        for l in self._lane_order
                    )
                    if _all_done:
                        self._log_info(f"ALL_WORK_COMPLETE {self._cache_summary()}")
                        self._maybe_log_health_locked(force=True)
                    self._cv.notify_all()

            if failed:
                self.invalidate_series(series_number, clear_disk=True)
                with self._lock:
                    need_reset = self._consecutive_failures >= self._max_consecutive_failures
                if need_reset:
                    self._failsafe_reset(reason=f"consecutive_failures>={self._max_consecutive_failures}")

            # ── CPU yield ──
            # After each heavy item (ITK processing can run 8-30s), yield the
            # CPU so the UI/rendering thread and download threads get a fair
            # share of processor time.  Warmup/background yield MUCH longer
            # because they are pure background work and must NEVER cause the
            # user to perceive lag on the interactive viewer path.
            # _GLOBAL_DOWNLOAD_ACTIVE: True when ANY patient is downloading,
            # even if this tab's own study is already complete.  Keeps warmup
            # from saturating CPU/GIL while an unrelated study downloads.
            _any_dl = self._download_active or _GLOBAL_DOWNLOAD_ACTIVE
            if lane == "interactive":
                time.sleep(0.08)   # 80ms — small yield for interactive
            elif _any_dl:
                time.sleep(2.0)    # 2s — very generous yield when ANY download active
            else:
                time.sleep(0.5)    # 500ms — generous yield for background warmup

    def _clear_cache_locked(self):
        old_entries = len(self._cache_order)
        old_bytes = self._cache_bytes
        self._cache.clear()
        self._cache_order.clear()
        self._cache_bytes = 0
        if old_entries or old_bytes:
            old_mb = old_bytes / (1024 * 1024)
            self._log_info(f"CACHE_CLEARED removed_entries={old_entries} removed_bytes={old_mb:.1f}MB tab={self.tab_key}")

    def _evict_locked(self):
        removed = 0
        while len(self._cache_order) > self._max_entries or self._cache_bytes > self._byte_budget:
            old = None
            # Prefer evicting non-protected entries first.
            for candidate in self._cache_order:
                if candidate not in self._protected_series:
                    old = candidate
                    break
            # If all entries are protected, evict oldest anyway to respect hard budget.
            if old is None and self._cache_order:
                old = self._cache_order[0]
            if old is None:
                break
            try:
                self._cache_order.remove(old)
            except Exception:
                if self._cache_order:
                    old = self._cache_order.pop(0)
                else:
                    break
            if old in self._cache:
                try:
                    _rvtk, _rmeta, rbytes = self._cache[old]
                    self._cache_bytes = max(0, self._cache_bytes - int(rbytes or 0))
                except Exception:
                    pass
                del self._cache[old]
                removed += 1
        if removed:
            self._log_info(f"EVICT removed={removed} {self._cache_summary()}")
