"""Worker loop: ensure workers, disk promotion, memory check, failsafe"""
# Auto-generated from engine.py — Phase 4 split
import threading
import time

from . import _zb_globals
from ._zb_globals import _set_thread_low_priority


class _ZBWorkersMixin:
    """Worker loop: ensure workers, disk promotion, memory check, failsafe"""

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

            _job_t0 = time.time()
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
                _job_elapsed_ms = (time.time() - _job_t0) * 1000.0
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
                        f"series={series_number} elapsed_ms={_job_elapsed_ms:.0f} {self._cache_summary()}"
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
            _any_dl = self._download_active or _zb_globals._GLOBAL_DOWNLOAD_ACTIVE
            if lane == "interactive":
                time.sleep(0.08)   # 80ms — small yield for interactive
            elif _any_dl:
                time.sleep(2.0)    # 2s — very generous yield when ANY download active
            else:
                time.sleep(0.5)    # 500ms — generous yield for background warmup
