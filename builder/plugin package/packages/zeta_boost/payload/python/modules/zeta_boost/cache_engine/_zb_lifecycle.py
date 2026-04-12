"""Lifecycle & state: activate/deactivate, download state, health, global lock, boost mode"""
# Auto-generated from engine.py — Phase 4 split
import time


class _ZBLifecycleMixin:
    """Lifecycle & state: activate/deactivate, download state, health, global lock, boost mode"""

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
        # Join worker threads outside the lock to avoid deadlocks.
        # Daemon threads would exit with the process, but joining ensures
        # they finish any in-progress cache writes or DB updates cleanly.
        for lane in self._lane_order:
            for th in self._worker_threads.get(lane, []):
                if th.is_alive():
                    th.join(timeout=3.0)
                    if th.is_alive():
                        self._log_info(f"⚠️ {lane} worker did not exit within 3s")

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

    def is_image_boost_mode(self) -> bool:
        """True during Mode B (image-level boost only; series cache disabled)."""
        with self._lock:
            return bool(self._image_boost_mode)
