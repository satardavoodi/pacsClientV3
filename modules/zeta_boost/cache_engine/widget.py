from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Optional

from ..disk_cache import ZetaBoostDiskCache

# Re-export module-level utilities from _zb_globals (avoids circular imports)
from ._zb_globals import set_global_download_active, _set_thread_low_priority  # noqa: F401

# ── Mixin imports ──
from ._zb_cache import _ZBCacheMixin
from ._zb_lanes import _ZBLanesMixin
from ._zb_workers import _ZBWorkersMixin
from ._zb_lifecycle import _ZBLifecycleMixin


class ZetaBoostEngine(_ZBCacheMixin, _ZBLanesMixin, _ZBWorkersMixin, _ZBLifecycleMixin):
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

