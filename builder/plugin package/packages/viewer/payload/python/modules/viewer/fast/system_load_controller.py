"""Centralized load-policy helpers for FAST viewer orchestration.

This is intentionally small: it does not schedule work itself.  It only
collects a few shared probes and returns conservative policies for existing
call sites so the UI-facing path can stay consistent under mixed load.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


_UI_LAG_OVERLOAD_MS = 50.0
_UI_LAG_STALE_MS = 750.0


class WorkClass(Enum):
    INTERACTION = "interaction"
    FINAL_RENDER = "final_render"
    PROGRESS_UPDATE = "progress_update"
    PROGRESSIVE_SIGNAL = "progressive_signal"
    PROGRESSIVE_GROW = "progressive_grow"
    THUMBNAIL_UI = "thumbnail_ui"
    PREFETCH = "prefetch"
    CACHE_WARM = "cache_warm"
    DIAGNOSTIC_LOG = "diagnostic_log"


class BlockId(Enum):
    BLOCK_1_DATA_SERVICES = "block_1_data_services"
    BLOCK_2_VIEWER_HOT_PATH = "block_2_viewer_hot_path"
    BLOCK_3_CACHE_SCROLL_ORCHESTRATION = "block_3_cache_scroll_orchestration"


@dataclass(frozen=True)
class LoadSnapshot:
    timestamp_ms: float
    fast_interaction_active: bool
    heavy_download_active: bool
    ui_event_loop_lag_ms: float
    protected_ui_cadence: bool
    prefetch_shedding_active: bool


@dataclass(frozen=True)
class WorkPolicy:
    work_class: WorkClass
    coalesce_interval_ms: float = 0.0
    defer_during_protected_ui: bool = False
    drop_if_overloaded: bool = False
    radius_cap: Optional[int] = None


_WORK_CLASS_TO_BLOCK: dict[WorkClass, BlockId] = {
    WorkClass.INTERACTION: BlockId.BLOCK_2_VIEWER_HOT_PATH,
    WorkClass.FINAL_RENDER: BlockId.BLOCK_2_VIEWER_HOT_PATH,
    WorkClass.PROGRESS_UPDATE: BlockId.BLOCK_1_DATA_SERVICES,
    WorkClass.THUMBNAIL_UI: BlockId.BLOCK_1_DATA_SERVICES,
    WorkClass.PROGRESSIVE_SIGNAL: BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION,
    WorkClass.PROGRESSIVE_GROW: BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION,
    WorkClass.PREFETCH: BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION,
    WorkClass.CACHE_WARM: BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION,
    WorkClass.DIAGNOSTIC_LOG: BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION,
}


_ADMISSION_OUTCOMES = ("admitted", "deferred", "dropped")


class SystemLoadController:
    """Shared, thread-safe probe store with conservative FAST policies."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fast_interaction_until_ms: float = 0.0
        self._last_ui_tick_ms: float = -1.0
        self._ui_lag_ms: float = 0.0
        self._ui_lag_updated_ms: float = -1.0
        self._last_admitted_ms: dict[tuple[str, str], float] = {}
        self._admission_counts: dict[str, dict[str, int]] = {}
        self._block_admission_counts: dict[str, dict[str, int]] = {}

    @staticmethod
    def classify_work_class(work_class: WorkClass | str) -> BlockId:
        wc = work_class if isinstance(work_class, WorkClass) else WorkClass(str(work_class))
        return _WORK_CLASS_TO_BLOCK.get(wc, BlockId.BLOCK_3_CACHE_SCROLL_ORCHESTRATION)

    @staticmethod
    def _now_ms() -> float:
        return time.monotonic() * 1000.0

    def update_fast_interaction(
        self,
        active: bool,
        *,
        grace_ms: float = 250.0,
        now_ms: Optional[float] = None,
    ) -> None:
        now = self._now_ms() if now_ms is None else float(now_ms)
        with self._lock:
            if active:
                self._fast_interaction_until_ms = max(
                    self._fast_interaction_until_ms,
                    now + float(grace_ms),
                )
            else:
                self._fast_interaction_until_ms = 0.0

    def is_fast_interaction_active(self, *, now_ms: Optional[float] = None) -> bool:
        now = self._now_ms() if now_ms is None else float(now_ms)
        with self._lock:
            return now < self._fast_interaction_until_ms

    def record_ui_tick(
        self,
        *,
        nominal_interval_ms: float = 16.0,
        now_ms: Optional[float] = None,
    ) -> float:
        """Record a UI-thread callback gap and return the current lag estimate."""
        now = self._now_ms() if now_ms is None else float(now_ms)
        with self._lock:
            lag = 0.0
            if self._last_ui_tick_ms >= 0.0:
                gap = now - self._last_ui_tick_ms
                lag = max(0.0, gap - float(nominal_interval_ms))
                if lag > self._ui_lag_ms:
                    self._ui_lag_ms = lag
                else:
                    # Decay toward normal when the UI starts recovering.
                    self._ui_lag_ms = max(lag, self._ui_lag_ms * 0.5)
                self._ui_lag_updated_ms = now
            self._last_ui_tick_ms = now
            return self._ui_lag_ms

    def get_ui_event_loop_lag_ms(self, *, now_ms: Optional[float] = None) -> float:
        now = self._now_ms() if now_ms is None else float(now_ms)
        with self._lock:
            if self._ui_lag_updated_ms < 0.0:
                return 0.0
            if now - self._ui_lag_updated_ms > _UI_LAG_STALE_MS:
                return 0.0
            return max(0.0, self._ui_lag_ms)

    def reset_ui_tick_baseline(self) -> None:
        """Clear the UI-tick baseline so the next record_ui_tick() establishes
        a fresh reference point.

        Without this, ``ui_lag_ms`` leaks between unrelated drag sessions:
        an idle gap of 10s between two drags would be reported as a 10s lag
        spike at the start of the second drag, drowning out real signal.
        Call at the start of each drag session.
        """
        with self._lock:
            self._last_ui_tick_ms = -1.0
            self._ui_lag_ms = 0.0
            self._ui_lag_updated_ms = -1.0

    def snapshot(
        self,
        *,
        heavy_download_active: bool,
        now_ms: Optional[float] = None,
    ) -> LoadSnapshot:
        now = self._now_ms() if now_ms is None else float(now_ms)
        fast = self.is_fast_interaction_active(now_ms=now)
        lag = self.get_ui_event_loop_lag_ms(now_ms=now)
        protected = fast or bool(heavy_download_active) or lag > _UI_LAG_OVERLOAD_MS
        shed_prefetch = fast or bool(heavy_download_active) or lag > _UI_LAG_OVERLOAD_MS
        return LoadSnapshot(
            timestamp_ms=now,
            fast_interaction_active=fast,
            heavy_download_active=bool(heavy_download_active),
            ui_event_loop_lag_ms=lag,
            protected_ui_cadence=protected,
            prefetch_shedding_active=shed_prefetch,
        )

    def policy_for(
        self,
        work_class: WorkClass,
        *,
        heavy_download_active: bool,
        fast_interaction_active: Optional[bool] = None,
        interaction_mode: str = '',
        now_ms: Optional[float] = None,
    ) -> WorkPolicy:
        snap = self.snapshot(
            heavy_download_active=heavy_download_active,
            now_ms=now_ms,
        )
        protected = (
            snap.protected_ui_cadence
            if fast_interaction_active is None
            else bool(fast_interaction_active) or snap.heavy_download_active or snap.ui_event_loop_lag_ms > _UI_LAG_OVERLOAD_MS
        )

        if work_class is WorkClass.PROGRESSIVE_SIGNAL:
            # v2.3.5 Fix 4: during heavy download + fast interaction, use
            # 750ms coalesce to further reduce main-thread churn.
            if protected and snap.heavy_download_active:
                fast = snap.fast_interaction_active if fast_interaction_active is None else bool(fast_interaction_active)
                interval = 750.0 if fast else 500.0
            elif protected:
                interval = 500.0
            else:
                interval = 100.0
            return WorkPolicy(
                work_class=work_class,
                coalesce_interval_ms=interval,
            )
        if work_class is WorkClass.PROGRESS_UPDATE:
            if protected and snap.heavy_download_active:
                fast = snap.fast_interaction_active if fast_interaction_active is None else bool(fast_interaction_active)
                interval = 750.0 if fast else 500.0
            elif protected:
                interval = 500.0
            else:
                interval = 200.0
            return WorkPolicy(
                work_class=work_class,
                coalesce_interval_ms=interval,
                defer_during_protected_ui=protected,
                drop_if_overloaded=protected,
            )
        if work_class is WorkClass.PROGRESSIVE_GROW:
            if protected and snap.heavy_download_active:
                fast = snap.fast_interaction_active if fast_interaction_active is None else bool(fast_interaction_active)
                interval = 750.0 if fast else 500.0
            elif protected:
                interval = 400.0
            else:
                interval = 150.0
            return WorkPolicy(
                work_class=work_class,
                coalesce_interval_ms=interval,
                defer_during_protected_ui=protected,
            )
        if work_class is WorkClass.THUMBNAIL_UI:
            return WorkPolicy(
                work_class=work_class,
                coalesce_interval_ms=500.0 if protected else 100.0,
                defer_during_protected_ui=protected,
            )
        if work_class is WorkClass.DIAGNOSTIC_LOG:
            return WorkPolicy(
                work_class=work_class,
                coalesce_interval_ms=500.0 if protected else 250.0,
                drop_if_overloaded=protected,
            )
        if work_class is WorkClass.PREFETCH:
            # v2.3.5 Fix 4: harsher mixed-load throttle.
            # During heavy download + fast interaction (scroll), cap to 1
            # to minimize background decode CPU contention that causes
            # 20-40ms set_slice spikes on the main thread.
            # During heavy download alone (no scroll), keep cap at 3.
            if protected:
                fast = snap.fast_interaction_active if fast_interaction_active is None else bool(fast_interaction_active)
                if fast and snap.heavy_download_active:
                    radius = 2 if str(interaction_mode or '') == 'drag' else 1
                else:
                    radius = 3
            else:
                radius = None
            return WorkPolicy(
                work_class=work_class,
                radius_cap=radius,
                defer_during_protected_ui=protected,
            )
        if work_class is WorkClass.CACHE_WARM:
            interval = 750.0 if protected else 0.0
            return WorkPolicy(
                work_class=work_class,
                coalesce_interval_ms=interval,
                defer_during_protected_ui=protected,
            )
        return WorkPolicy(work_class=work_class)

    def _record_admission_outcome(self, work_class: WorkClass, outcome: str) -> None:
        if outcome not in _ADMISSION_OUTCOMES:
            return
        block_id = self.classify_work_class(work_class)
        with self._lock:
            bucket = self._admission_counts.setdefault(
                work_class.value,
                {name: 0 for name in _ADMISSION_OUTCOMES},
            )
            bucket[outcome] += 1
            block_bucket = self._block_admission_counts.setdefault(
                block_id.value,
                {name: 0 for name in _ADMISSION_OUTCOMES},
            )
            block_bucket[outcome] += 1

    def admission_stats(self, *, reset: bool = False) -> dict[str, dict[str, int]]:
        """Return per-work-class admitted/deferred/dropped counters."""
        with self._lock:
            snapshot = {
                work_class: dict(counts)
                for work_class, counts in self._admission_counts.items()
            }
            if reset:
                self._admission_counts = {}
        return snapshot

    def block_admission_stats(self, *, reset: bool = False) -> dict[str, dict[str, int]]:
        """Return admitted/deferred/dropped counters grouped by functional block."""
        with self._lock:
            snapshot = {
                block_id: dict(counts)
                for block_id, counts in self._block_admission_counts.items()
            }
            if reset:
                self._block_admission_counts = {}
        return snapshot

    def debug_snapshot(
        self,
        *,
        heavy_download_active: bool,
        fast_interaction_active: Optional[bool] = None,
        now_ms: Optional[float] = None,
    ) -> dict[str, object]:
        now = self._now_ms() if now_ms is None else float(now_ms)
        snap = self.snapshot(
            heavy_download_active=heavy_download_active,
            now_ms=now,
        )
        fast = snap.fast_interaction_active if fast_interaction_active is None else bool(fast_interaction_active)
        return {
            "timestamp_ms": round(now, 2),
            "fast_interaction_active": bool(fast),
            "heavy_download_active": bool(heavy_download_active),
            "ui_event_loop_lag_ms": round(snap.ui_event_loop_lag_ms, 2),
            "protected_ui_cadence": bool(snap.protected_ui_cadence),
            "prefetch_shedding_active": bool(snap.prefetch_shedding_active),
            "admission_by_work_class": self.admission_stats(),
            "admission_by_block": self.block_admission_stats(),
        }

    def should_admit(
        self,
        task_type: WorkClass | str,
        context: Optional[dict] = None,
        *,
        heavy_download_active: bool,
        fast_interaction_active: Optional[bool] = None,
        now_ms: Optional[float] = None,
    ) -> bool:
        """Return True when the requested work should be admitted now.

        Tiering model:
        - Tier 1: INTERACTION / FINAL_RENDER — always admitted.
        - Tier 2: PREFETCH — distance-bounded and burst-coalesced.
        - Tier 3: progress/UI/background work — aggressively coalesced under
          protected UI so stale fan-out does not compete with the active slice.
        """
        ctx = context or {}
        now = self._now_ms() if now_ms is None else float(now_ms)
        work_class = task_type if isinstance(task_type, WorkClass) else WorkClass(str(task_type))
        policy = self.policy_for(
            work_class,
            heavy_download_active=heavy_download_active,
            fast_interaction_active=fast_interaction_active,
            interaction_mode=str(ctx.get("interaction_mode", "") or ""),
            now_ms=now,
        )

        if work_class in {WorkClass.INTERACTION, WorkClass.FINAL_RENDER}:
            self._record_admission_outcome(work_class, "admitted")
            return True

        if work_class is WorkClass.PROGRESSIVE_GROW:
            if bool(ctx.get("terminal", False)):
                self._record_admission_outcome(work_class, "admitted")
                return True
            admitted = not bool(policy.defer_during_protected_ui)
            self._record_admission_outcome(
                work_class,
                "admitted" if admitted else "deferred",
            )
            return admitted

        if work_class is WorkClass.PREFETCH:
            distance = abs(int(ctx.get("distance", 0) or 0))
            if policy.radius_cap is not None and distance > int(policy.radius_cap):
                self._record_admission_outcome(work_class, "dropped")
                return False
            key = str(ctx.get("key") or ctx.get("series_key") or "prefetch")
            min_interval_ms = 90.0 if (
                bool(policy.defer_during_protected_ui)
                or bool(heavy_download_active)
                or bool(fast_interaction_active)
            ) else 0.0
            with self._lock:
                last = self._last_admitted_ms.get((work_class.value, key))
                if last is not None and min_interval_ms > 0.0 and (now - last) < min_interval_ms:
                    deferred = True
                else:
                    self._last_admitted_ms[(work_class.value, key)] = now
                    deferred = False
            if deferred:
                self._record_admission_outcome(work_class, "deferred")
                return False
            self._record_admission_outcome(work_class, "admitted")
            return True

        if bool(ctx.get("identical", False)):
            self._record_admission_outcome(work_class, "dropped")
            return False

        key = str(ctx.get("key") or ctx.get("series_key") or work_class.value)
        if bool(ctx.get("force", False)):
            with self._lock:
                self._last_admitted_ms[(work_class.value, key)] = now
            self._record_admission_outcome(work_class, "admitted")
            return True

        interval = max(0.0, float(policy.coalesce_interval_ms or 0.0))
        if interval <= 0.0 and not bool(policy.defer_during_protected_ui):
            self._record_admission_outcome(work_class, "admitted")
            return True

        with self._lock:
            last = self._last_admitted_ms.get((work_class.value, key))
            if last is not None and interval > 0.0 and (now - last) < interval:
                deferred = True
            else:
                self._last_admitted_ms[(work_class.value, key)] = now
                deferred = False
        if deferred:
            self._record_admission_outcome(work_class, "deferred")
            return False
        self._record_admission_outcome(work_class, "admitted")
        return True

    def progressive_signal_interval_ms(
        self,
        *,
        heavy_download_active: bool,
        now_ms: Optional[float] = None,
    ) -> float:
        return self.policy_for(
            WorkClass.PROGRESSIVE_SIGNAL,
            heavy_download_active=heavy_download_active,
            now_ms=now_ms,
        ).coalesce_interval_ms

    def thumbnail_progress_interval_ms(
        self,
        *,
        heavy_download_active: bool,
        now_ms: Optional[float] = None,
    ) -> float:
        return self.policy_for(
            WorkClass.THUMBNAIL_UI,
            heavy_download_active=heavy_download_active,
            now_ms=now_ms,
        ).coalesce_interval_ms

    def progress_update_interval_ms(
        self,
        *,
        heavy_download_active: bool,
        fast_interaction_active: Optional[bool] = None,
        now_ms: Optional[float] = None,
    ) -> float:
        return self.policy_for(
            WorkClass.PROGRESS_UPDATE,
            heavy_download_active=heavy_download_active,
            fast_interaction_active=fast_interaction_active,
            now_ms=now_ms,
        ).coalesce_interval_ms

    def progressive_grow_interval_ms(
        self,
        *,
        heavy_download_active: bool,
        fast_interaction_active: Optional[bool] = None,
        now_ms: Optional[float] = None,
    ) -> float:
        return self.policy_for(
            WorkClass.PROGRESSIVE_GROW,
            heavy_download_active=heavy_download_active,
            fast_interaction_active=fast_interaction_active,
            now_ms=now_ms,
        ).coalesce_interval_ms

    def thumbnail_log_interval_ms(
        self,
        *,
        heavy_download_active: bool,
        now_ms: Optional[float] = None,
    ) -> float:
        return self.policy_for(
            WorkClass.DIAGNOSTIC_LOG,
            heavy_download_active=heavy_download_active,
            now_ms=now_ms,
        ).coalesce_interval_ms

    def cap_prefetch_radius(
        self,
        base_radius: int,
        *,
        fast_interaction_active: bool,
        heavy_download_active: bool,
        interaction_mode: str = '',
        now_ms: Optional[float] = None,
    ) -> int:
        if int(base_radius) <= 0:
            return 0
        policy = self.policy_for(
            WorkClass.PREFETCH,
            heavy_download_active=heavy_download_active,
            fast_interaction_active=fast_interaction_active,
            interaction_mode=interaction_mode,
            now_ms=now_ms,
        )
        if policy.radius_cap is None:
            return int(base_radius)
        return min(int(base_radius), int(policy.radius_cap))


_GLOBAL_SYSTEM_LOAD_CONTROLLER = SystemLoadController()


def get_system_load_controller() -> SystemLoadController:
    return _GLOBAL_SYSTEM_LOAD_CONTROLLER
