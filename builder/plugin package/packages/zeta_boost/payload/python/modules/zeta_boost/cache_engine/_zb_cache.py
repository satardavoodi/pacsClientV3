"""Cache operations: query, get, put, trim, clear, evict, invalidate"""
# Auto-generated from engine.py — Phase 4 split
import threading
import time


class _ZBCacheMixin:
    """Cache operations: query, get, put, trim, clear, evict, invalidate"""

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

                threading.Thread(
                    target=_async_disk_write,
                    daemon=True,
                    name=f"ZB-DiskW-{key[:20]}",
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
