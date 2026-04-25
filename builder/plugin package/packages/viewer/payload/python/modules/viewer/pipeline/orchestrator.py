"""Pipeline Orchestrator — deterministic state machine for the viewer pipeline.

Modes
-----
Mode A  (pre-downloaded)
    All series already on disk.  Immediately enters POST_DOWNLOAD.
    ZetaBoost warmup is allowed from the start.

Mode B  (concurrent download)
    Downloads are in progress.  Enters DOWNLOADING on first download signal.
    ZetaBoost warmup is BLOCKED until the definitive study-complete signal.
    Preview engine provides lightweight single-slice views during this phase.

Mode A+B  (mixed)
    Some series pre-exist, others streaming.  Enters DOWNLOADING for the
    streaming portion; POST_DOWNLOAD once the study-level signal arrives.

States
------
IDLE            Tab opened, no download or warmup initiated yet.
DOWNLOADING     Active downloads.  ZetaBoost dormant.  Preview engine active.
POST_DOWNLOAD   Study download complete.  ZetaBoost warmup may proceed.
READY           All series warmed/cached.  Full viewer performance.

Invariants
----------
- ZetaBoost warmup/background lanes are NEVER allowed during DOWNLOADING.
- Interactive user loads (drag-drop, scroll) are ALWAYS allowed in any state.
- Preview engine operates **only** during DOWNLOADING.
- State transitions emit a callback so the viewer controller can bridge
  the orchestrator's decisions to ZetaBoost engine and preview engine.
"""

from __future__ import annotations

from collections import Counter
from collections import deque
from dataclasses import asdict, dataclass
import threading
import time
from enum import Enum, auto
from typing import Callable, Optional, Set


@dataclass(frozen=True)
class PipelineEvent:
    seq: int
    timestamp_ms: float
    event: str
    owner_block: str
    state_before: str
    state_after: str
    active_download_count: int
    completed_series_count: int
    study_download_complete: bool
    series_number: str = ""
    study_uid: str = ""
    detail: str = ""


class PipelineState(Enum):
    IDLE = auto()
    DOWNLOADING = auto()
    POST_DOWNLOAD = auto()
    READY = auto()


class PipelineOrchestrator:
    """Central pipeline state machine.  Owned by ViewerController.

    Receives signals from:
      - home_ui        (download start / series complete / study complete)
      - viewer ctrl    (tab lifecycle, user interaction)

    Emits state changes to:
      - ZetaBoost engine   (set_study_download_complete)
      - preview engine     (active / idle)
      - viewer controller  (routing decisions)
    """

    # ------------------------------------------------------------------ init
    def __init__(
        self,
        *,
        on_state_changed: Optional[Callable[[PipelineState, PipelineState], None]] = None,
        logger=None,
    ):
        self._state: PipelineState = PipelineState.IDLE
        self._lock = threading.Lock()
        self._on_state_changed = on_state_changed
        self._logger = logger

        # Download tracking
        self._download_session_active: bool = False
        self._downloading_series: Set[str] = set()
        self._completed_series: Set[str] = set()
        self._study_download_complete: bool = False
        self._transition_seq: int = 0
        self._events: deque[PipelineEvent] = deque(maxlen=128)

        # Timestamps for diagnostics
        self._state_enter_ts: float = time.time()
        self._last_download_ts: float = 0.0

    # ------------------------------------------------------------ properties
    @property
    def state(self) -> PipelineState:
        with self._lock:
            return self._state

    @property
    def is_download_active(self) -> bool:
        with self._lock:
            return self._state == PipelineState.DOWNLOADING

    @property
    def active_download_count(self) -> int:
        """Number of series currently downloading in this orchestrator."""
        with self._lock:
            return len(self._downloading_series)

    @property
    def is_warmup_allowed(self) -> bool:
        """True when ZetaBoost warmup may run (POST_DOWNLOAD or READY)."""
        with self._lock:
            return self._state in (PipelineState.POST_DOWNLOAD, PipelineState.READY)

    @property
    def is_preview_active(self) -> bool:
        """True when the lightweight preview engine should generate previews."""
        with self._lock:
            return self._state == PipelineState.DOWNLOADING

    def is_series_downloading(self, series_number) -> bool:
        """True when the specific series is still downloading."""
        with self._lock:
            return str(series_number) in self._downloading_series

    def is_heavy_download_active(self) -> bool:
        """True when this orchestrator has active per-series download work."""
        with self._lock:
            return self._state == PipelineState.DOWNLOADING and bool(self._downloading_series)

    def is_series_downloaded(self, series_number) -> bool:
        with self._lock:
            return (
                str(series_number) in self._completed_series
                or self._study_download_complete
            )

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            event_counts_by_block = Counter(event.owner_block for event in self._events)
            event_counts_by_name = Counter(event.event for event in self._events)
            most_recent_event = asdict(self._events[-1]) if self._events else None
            return {
                "state": self._state.name,
                "download_session_active": bool(self._download_session_active),
                "active_download_count": len(self._downloading_series),
                "completed_series_count": len(self._completed_series),
                "transition_seq": self._transition_seq,
                "study_download_complete": bool(self._study_download_complete),
                "state_duration_ms": round((now - self._state_enter_ts) * 1000.0, 2),
                "last_download_age_ms": round((now - self._last_download_ts) * 1000.0, 2) if self._last_download_ts else 0.0,
                "downloading_series": sorted(self._downloading_series),
                "completed_series": sorted(self._completed_series),
                "most_recent_event": most_recent_event,
                "event_counts_by_block": dict(event_counts_by_block),
                "event_counts_by_name": dict(event_counts_by_name),
                "recent_events": [asdict(event) for event in self._events],
            }

    # ------------------------------------------------------ download signals
    def on_download_session_started(self, study_uid: str = ""):
        """Called when a study download is initiated."""
        with self._lock:
            self._download_session_active = True
            self._study_download_complete = False
            old = self._state
            self._state = PipelineState.DOWNLOADING
            self._state_enter_ts = time.time()
            changed = old != PipelineState.DOWNLOADING
            self._record_event_locked(
                event="download_session_started",
                owner_block="block_1_data_services",
                state_before=old,
                state_after=self._state,
                study_uid=str(study_uid or ""),
            )
        self._log(f"DOWNLOAD_SESSION_START study={study_uid[:30] if study_uid else ''}")
        if changed:
            self._notify(old, PipelineState.DOWNLOADING)

    def on_series_download_started(self, series_number):
        """Called when a single series starts downloading."""
        with self._lock:
            self._downloading_series.add(str(series_number))
            if not self._download_session_active:
                self._download_session_active = True
                old = self._state
                if old != PipelineState.DOWNLOADING:
                    self._state = PipelineState.DOWNLOADING
                    self._state_enter_ts = time.time()
                    need_notify = True
                else:
                    need_notify = False
            else:
                need_notify = False
                old = self._state
            self._record_event_locked(
                event="series_download_started",
                owner_block="block_1_data_services",
                state_before=old,
                state_after=self._state,
                series_number=str(series_number),
            )
        if need_notify:
            self._notify(old, PipelineState.DOWNLOADING)

    def on_series_download_completed(self, series_number):
        """Called when a single series finishes downloading."""
        key = str(series_number)
        with self._lock:
            self._completed_series.add(key)
            self._downloading_series.discard(key)
            self._last_download_ts = time.time()

            # GUARD: Never regress from POST_DOWNLOAD/READY back to DOWNLOADING.
            # In Mode A (pre-downloaded), mark_pre_downloaded() already advanced
            # to POST_DOWNLOAD.  Local-first-series loads emit series_downloaded
            # which would corrupt the state without this guard.
            if self._state in (PipelineState.POST_DOWNLOAD, PipelineState.READY):
                need_notify = False
                old = self._state
            elif not self._download_session_active:
                # Auto-enter DOWNLOADING state if idle and a series arrives
                self._download_session_active = True
                old = self._state
                if old != PipelineState.DOWNLOADING:
                    self._state = PipelineState.DOWNLOADING
                    self._state_enter_ts = time.time()
                    need_notify = True
                else:
                    need_notify = False
            else:
                need_notify = False
                old = self._state
            self._record_event_locked(
                event="series_download_completed",
                owner_block="block_1_data_services",
                state_before=old,
                state_after=self._state,
                series_number=key,
            )
        self._log(
            f"SERIES_DOWNLOAD_COMPLETE series={key} state={self._state.name} "
            f"total_completed={len(self._completed_series)}"
        )
        if need_notify:
            self._notify(old, PipelineState.DOWNLOADING)

    def on_study_download_completed(self, study_uid: str = ""):
        """Definitive signal: ALL series in the study have finished.

        This is the ONLY trigger that transitions DOWNLOADING → POST_DOWNLOAD.
        ZetaBoost warmup is allowed only after this signal.
        """
        with self._lock:
            self._study_download_complete = True
            self._download_session_active = False
            old = self._state
            self._state = PipelineState.POST_DOWNLOAD
            self._state_enter_ts = time.time()
            changed = old != PipelineState.POST_DOWNLOAD
            self._record_event_locked(
                event="study_download_completed",
                owner_block="block_3_cache_scroll_orchestration",
                state_before=old,
                state_after=self._state,
                study_uid=str(study_uid or ""),
            )
        self._log(
            f"STUDY_DOWNLOAD_COMPLETE study={study_uid[:30] if study_uid else ''} "
            f"completed_series={len(self._completed_series)}"
        )
        if changed:
            self._notify(old, PipelineState.POST_DOWNLOAD)

    # ------------------------------------------------ Mode A: pre-downloaded
    def mark_pre_downloaded(self):
        """Mode A shortcut: all images already on disk — skip to POST_DOWNLOAD."""
        with self._lock:
            self._study_download_complete = True
            self._download_session_active = False
            old = self._state
            self._state = PipelineState.POST_DOWNLOAD
            self._state_enter_ts = time.time()
            changed = old != PipelineState.POST_DOWNLOAD
            self._record_event_locked(
                event="mark_pre_downloaded",
                owner_block="block_3_cache_scroll_orchestration",
                state_before=old,
                state_after=self._state,
            )
        self._log("PRE_DOWNLOADED mode=A")
        if changed:
            self._notify(old, PipelineState.POST_DOWNLOAD)

    # --------------------------------------------------- warmup completion
    def on_all_warmed_up(self):
        """All series cached — transition POST_DOWNLOAD → READY."""
        with self._lock:
            if self._state != PipelineState.POST_DOWNLOAD:
                return
            old = self._state
            self._state = PipelineState.READY
            self._state_enter_ts = time.time()
            self._record_event_locked(
                event="all_warmed_up",
                owner_block="block_3_cache_scroll_orchestration",
                state_before=old,
                state_after=self._state,
            )
        self._log("ALL_WARMED_UP → READY")
        self._notify(old, PipelineState.READY)

    # ----------------------------------------------------------- lifecycle
    def reset(self):
        with self._lock:
            old = self._state
            self._state = PipelineState.IDLE
            self._download_session_active = False
            self._downloading_series.clear()
            self._completed_series.clear()
            self._study_download_complete = False
            self._state_enter_ts = time.time()
            changed = old != PipelineState.IDLE
            self._record_event_locked(
                event="reset",
                owner_block="block_3_cache_scroll_orchestration",
                state_before=old,
                state_after=self._state,
            )
        if changed:
            self._notify(old, PipelineState.IDLE)

    # ----------------------------------------------------------- internals
    def _notify(self, old: PipelineState, new: PipelineState):
        cb = self._on_state_changed
        if cb:
            try:
                cb(old, new)
            except Exception:
                pass

    def _record_event_locked(
        self,
        *,
        event: str,
        owner_block: str,
        state_before: PipelineState,
        state_after: PipelineState,
        series_number: str = "",
        study_uid: str = "",
        detail: str = "",
    ) -> None:
        self._transition_seq += 1
        self._events.append(
            PipelineEvent(
                seq=self._transition_seq,
                timestamp_ms=round(time.time() * 1000.0, 2),
                event=str(event),
                owner_block=str(owner_block),
                state_before=state_before.name,
                state_after=state_after.name,
                active_download_count=len(self._downloading_series),
                completed_series_count=len(self._completed_series),
                study_download_complete=bool(self._study_download_complete),
                series_number=str(series_number or ""),
                study_uid=str(study_uid or ""),
                detail=str(detail or ""),
            )
        )

    def _log(self, msg: str):
        full = f"[Pipeline] state={self._state.name} {msg}"
        try:
            print(full)
        except Exception:
            pass
        if self._logger:
            try:
                self._logger.info(full)
            except Exception:
                pass
