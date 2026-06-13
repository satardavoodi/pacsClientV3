"""Thread-safe Upload Manager state store with observers (ADR-0009 D2).

Mirrors the Download Manager's store/observer separation but is intentionally
lighter (in-memory; the durable per-file resume state already lives in
``consultation_db``). Observers are plain callables ``(event, job_id, state)`` so
the UI layer can subscribe without this module importing Qt.
"""
from __future__ import annotations

import threading
from typing import Callable, Dict, List, Optional

from ..core.models import UploadJobState

Observer = Callable[[str, str, UploadJobState], None]


class UploadStateStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: Dict[str, UploadJobState] = {}
        self._observers: List[Observer] = []

    def add_observer(self, obs: Observer) -> None:
        with self._lock:
            if obs not in self._observers:
                self._observers.append(obs)

    def remove_observer(self, obs: Observer) -> None:
        with self._lock:
            if obs in self._observers:
                self._observers.remove(obs)

    def create(self, state: UploadJobState) -> UploadJobState:
        with self._lock:
            self._states[state.job_id] = state
        self._notify("created", state.job_id, state)
        return state

    def get(self, job_id: str) -> Optional[UploadJobState]:
        with self._lock:
            return self._states.get(job_id)

    def all(self) -> List[UploadJobState]:
        with self._lock:
            return list(self._states.values())

    def update(self, job_id: str, **changes) -> Optional[UploadJobState]:
        with self._lock:
            st = self._states.get(job_id)
            if st is None:
                return None
            for k, v in changes.items():
                if hasattr(st, k):
                    setattr(st, k, v)
        self._notify("updated", job_id, st)
        return st

    def touch(self, job_id: str) -> None:
        """Emit an 'updated' event after in-place mutation (e.g. note_progress)."""
        st = self.get(job_id)
        if st is not None:
            self._notify("updated", job_id, st)

    def remove(self, job_id: str) -> None:
        with self._lock:
            st = self._states.pop(job_id, None)
        if st is not None:
            self._notify("removed", job_id, st)

    def _notify(self, event: str, job_id: str, state: UploadJobState) -> None:
        for obs in list(self._observers):
            try:
                obs(event, job_id, state)
            except Exception:
                # An observer must never break the store (mirrors DM discipline).
                pass


_STORE: Optional[UploadStateStore] = None
_STORE_LOCK = threading.Lock()


def get_state_store() -> UploadStateStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = UploadStateStore()
        return _STORE
