"""Single per-series download/display state authority (unified viewer pipeline).

S0 of ``docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md``. **Pure stdlib
+ threading** (no Qt / VTK / pydicom / numpy). Introduced **UNUSED** in S0 so the contract can
be locked and unit-tested before any production holder is rerouted (zero runtime risk). The
store is backend-agnostic — FAST and Advanced project the same states from it.

What it replaces (S2)
---------------------
Today a series' "where is it in its lifecycle" is smeared across **6 parallel holders** with
no single owner: ``PipelineOrchestrator``, the DM ``state_store``, the ``_progressive_*`` sets,
``_loading_series_numbers``, ``vtk._awaiting_series_number``, and the decoded caches. They
disagree, and the disagreements are the bugs:

* the 47855 **ownership leak** (``_loading_series_numbers`` left a series "loading" forever
  after a stale-return) → here ownership release is part of the same atomic transition, so it
  cannot leak;
* the **99→8 displayed-count downgrade** → here ``displayed_count`` is monotonic unless an
  explicit reset, so a stale smaller count cannot overwrite a larger one;
* the **F1** preempt reading a stale snapshot → here every reader sees one locked record.

When S2 routes the holders to read/write this store, those guard flags
(``AIPACS_LOAD_OWNERSHIP_RELEASE_ON_STALE``, ``AIPACS_CRITICAL_INTENT_FRESH_STATE``,
``AIPACS_RESUME_STOP_WHEN_SETTLED`` …) can retire.

State model
-----------
``REQUESTED → QUEUED → DOWNLOADING → PARTIAL_ON_DISK → DECODING → DISPLAYED`` (monotonic), with
``* → FAILED`` always allowed, and the single sanctioned *backward* edge
``{PARTIAL_ON_DISK, DISPLAYED} → DOWNLOADING`` for a server-grew re-fetch. Disk is authority for
existence; ``target = max(disk_count, expected_count)`` (mirrors
``series_display_state.py``).
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple

# Diagnostic shadow (S0): opt-in. When on, callers may compare what the store WOULD decide
# against the live path. Default OFF — the store is unused in S0, so this stays quiet.
_VIEWER_SPINE_SHADOW = (os.getenv("AIPACS_VIEWER_SPINE_SHADOW", "0") or "0").strip() == "1"


def shadow_enabled() -> bool:
    return _VIEWER_SPINE_SHADOW


class SeriesState(Enum):
    REQUESTED = "requested"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PARTIAL_ON_DISK = "partial_on_disk"
    DECODING = "decoding"
    DISPLAYED = "displayed"
    FAILED = "failed"


# Linear progress order (FAILED is intentionally OUTSIDE the order — handled explicitly).
_ORDER: Dict[SeriesState, int] = {
    SeriesState.REQUESTED: 0,
    SeriesState.QUEUED: 1,
    SeriesState.DOWNLOADING: 2,
    SeriesState.PARTIAL_ON_DISK: 3,
    SeriesState.DECODING: 4,
    SeriesState.DISPLAYED: 5,
}
# The only sanctioned backward edge: a server-grew re-fetch.
_REFETCH_FROM = {SeriesState.PARTIAL_ON_DISK, SeriesState.DISPLAYED}


def can_transition(cur: SeriesState, new: SeriesState) -> bool:
    """Pure transition predicate (also used directly by tests)."""
    if new == SeriesState.FAILED:
        return True
    if cur == SeriesState.FAILED:
        return True  # retry from failure
    if cur == new:
        return True  # idempotent (count refresh)
    if _ORDER[new] > _ORDER[cur]:
        return True  # forward (skips allowed)
    # backward: only re-fetch into DOWNLOADING
    return new == SeriesState.DOWNLOADING and cur in _REFETCH_FROM


@dataclass
class SeriesRecord:
    study_uid: str
    series_uid: str
    patient_id: str
    state: SeriesState = SeriesState.REQUESTED
    disk_count: int = 0
    expected_count: int = 0
    displayed_count: int = 0
    owner_handle: Optional[str] = None  # ViewerHandle.uuid currently loading this series
    error: Optional[str] = None
    updated_ts: float = field(default_factory=time.time)

    @property
    def target_count(self) -> int:
        """What SHOULD be shown: disk is authority, expected is the server hint."""
        return max(int(self.disk_count or 0), int(self.expected_count or 0))

    @property
    def is_settled(self) -> bool:
        """Displayed and showing the full target — the 'stop the resume watchdog' condition."""
        return (self.state == SeriesState.DISPLAYED
                and self.target_count > 0
                and self.displayed_count >= self.target_count)


class SeriesStateStore:
    """Thread-safe authority keyed by ``(study_uid, series_uid)`` (globally unique).

    Every mutation takes the lock; readers get a copy, so no caller can observe a half-applied
    transition. ``patient_id`` is stored on the record and a transition that tries to change it
    is rejected — cross-patient isolation is enforced at the store, structurally.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: Dict[Tuple[str, str], SeriesRecord] = {}

    # -- internal ---------------------------------------------------------- #
    @staticmethod
    def _key(study_uid, series_uid) -> Tuple[str, str]:
        return (str(study_uid or "").strip(), str(series_uid or "").strip())

    # -- reads ------------------------------------------------------------- #
    def get(self, study_uid, series_uid) -> Optional[SeriesRecord]:
        with self._lock:
            rec = self._records.get(self._key(study_uid, series_uid))
            return None if rec is None else _copy(rec)

    def is_owner(self, study_uid, series_uid, handle_uuid) -> bool:
        with self._lock:
            rec = self._records.get(self._key(study_uid, series_uid))
            return bool(rec and rec.owner_handle and rec.owner_handle == _huuid(handle_uuid))

    def snapshot(self) -> Dict[Tuple[str, str], SeriesRecord]:
        with self._lock:
            return {k: _copy(v) for k, v in self._records.items()}

    # -- writes ------------------------------------------------------------ #
    def request(self, req, *, expected: Optional[int] = None) -> SeriesRecord:
        """Register/claim a series for a viewer handle (enters REQUESTED, sets ownership).

        ``req`` is a ``PacsClient.utils.viewer_identity.SeriesRequest`` (duck-typed here to keep
        this module import-light — only ``.study_uid/.series_uid/.patient_id/.viewer_handle``
        are read)."""
        key = self._key(req.study_uid, req.series_uid)
        huuid = _huuid(getattr(req, "viewer_handle", None))
        with self._lock:
            rec = self._records.get(key)
            if rec is None:
                rec = SeriesRecord(
                    study_uid=key[0], series_uid=key[1],
                    patient_id=str(getattr(req, "patient_id", "") or "").strip(),
                )
                self._records[key] = rec
            # Ownership handover is explicit: a new request takes the slot.
            rec.owner_handle = huuid
            if expected is not None and int(expected) > 0:
                rec.expected_count = max(rec.expected_count, int(expected))
            rec.error = None
            rec.updated_ts = time.time()
            return _copy(rec)

    def transition(
        self,
        study_uid,
        series_uid,
        new_state: SeriesState,
        *,
        by_handle=None,
        require_owner: bool = False,
        disk: Optional[int] = None,
        expected: Optional[int] = None,
        displayed: Optional[int] = None,
        release_owner: bool = False,
        error: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Atomically advance a series. Returns ``(changed, reason)``.

        * ``require_owner`` — reject if ``by_handle`` is not the current owner (a stale worker
          can't mutate a series that a newer request has taken over: the F1 / ownership-leak
          fix made structural).
        * ``release_owner`` — clear ownership as part of THIS transition (atomic; the leak
          cannot happen because release is not a separate step).
        * ``displayed`` is monotonic (a smaller value is ignored unless ``new_state`` resets it
          via a re-fetch) — the 99→8 downgrade guard, structural.
        """
        key = self._key(study_uid, series_uid)
        h = _huuid(by_handle)
        with self._lock:
            rec = self._records.get(key)
            if rec is None:
                return (False, "unknown_series")
            if require_owner and rec.owner_handle and h and rec.owner_handle != h:
                return (False, "not_owner")
            if not can_transition(rec.state, new_state):
                return (False, f"illegal:{rec.state.value}->{new_state.value}")

            refetch = (new_state == SeriesState.DOWNLOADING and rec.state in _REFETCH_FROM)

            if disk is not None:
                rec.disk_count = max(int(rec.disk_count or 0), int(disk)) if not refetch else int(disk)
            if expected is not None and int(expected) > 0:
                rec.expected_count = int(expected) if refetch else max(rec.expected_count, int(expected))
            if displayed is not None:
                if refetch:
                    rec.displayed_count = int(displayed)
                else:
                    rec.displayed_count = max(int(rec.displayed_count or 0), int(displayed))

            rec.state = new_state
            if new_state == SeriesState.FAILED:
                rec.error = (error or "").strip() or "failed"
            if release_owner or new_state == SeriesState.FAILED:
                rec.owner_handle = None
            rec.updated_ts = time.time()
            return (True, "ok")

    def release(self, study_uid, series_uid, by_handle=None) -> bool:
        """Clear ownership without changing state (replaces the leaked
        ``_loading_series_numbers.discard``). No-op if ``by_handle`` is not the owner."""
        key = self._key(study_uid, series_uid)
        h = _huuid(by_handle)
        with self._lock:
            rec = self._records.get(key)
            if rec is None:
                return False
            if h and rec.owner_handle and rec.owner_handle != h:
                return False
            rec.owner_handle = None
            rec.updated_ts = time.time()
            return True

    def clear_patient(self, patient_id) -> int:
        """Drop all records for a patient (on tab close). Returns count removed."""
        pid = str(patient_id or "").strip()
        with self._lock:
            doomed = [k for k, r in self._records.items() if r.patient_id == pid]
            for k in doomed:
                del self._records[k]
            return len(doomed)


def _huuid(handle_or_uuid) -> Optional[str]:
    """Accept a ViewerHandle, its uuid string, or None."""
    if handle_or_uuid is None:
        return None
    u = getattr(handle_or_uuid, "uuid", None)
    return str(u if u is not None else handle_or_uuid).strip() or None


def _copy(rec: SeriesRecord) -> SeriesRecord:
    return SeriesRecord(
        study_uid=rec.study_uid, series_uid=rec.series_uid, patient_id=rec.patient_id,
        state=rec.state, disk_count=rec.disk_count, expected_count=rec.expected_count,
        displayed_count=rec.displayed_count, owner_handle=rec.owner_handle,
        error=rec.error, updated_ts=rec.updated_ts,
    )
