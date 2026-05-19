"""Lane management: normalize, enqueue, clear pending, lane-locked helpers"""
# Auto-generated from engine.py — Phase 4 split
import logging as _logging
from collections import deque
from typing import Optional

_zb_lanes_logger = _logging.getLogger(__name__)


class _ZBLanesMixin:
    """Lane management: normalize, enqueue, clear pending, lane-locked helpers"""

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
        engine_cls = self.__class__
        global_download_count = int(getattr(engine_cls, "_global_active_download_count", 0) or 0)
        if (global_download_count > 0
                and lane in ("warmup", "background")):
            _zb_lanes_logger.debug(
                "FAST:zetaboost_gate lane=%s reason=global_download_active count=%d",
                lane, global_download_count,
            )
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
            _zb_lanes_logger.debug(
                "FAST:zetaboost_gate lane=%s reason=study_download_pending "
                "study_download_complete=%s intentional=True",
                lane, self._study_download_complete,
            )
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
        engine_cls = self.__class__
        global_download_count = int(getattr(engine_cls, "_global_active_download_count", 0) or 0)
        if (global_download_count > 0
                and lane in ("warmup", "background")):
            reasons.append(
                f"global_download_active({global_download_count})"
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
