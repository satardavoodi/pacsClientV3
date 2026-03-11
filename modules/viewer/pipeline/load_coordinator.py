"""Load Coordinator — prevents duplicate DICOM loads across interactive/warmup.

Problem
-------
Without coordination, the same series can be loaded simultaneously by:
  1. Interactive drag-drop (user action)
  2. ZetaBoost warmup callback (background)
  3. First-series display task (async)

This creates 2-3× CPU/GIL/disk contention with zero benefit.

Solution
--------
A single lock-free coordinator tracks which series are in-flight.
Before starting a load, callers call ``try_acquire(series, owner)``:

  - ``('acquired', None)``  — this caller owns the load, must call ``complete()``
  - ``('wait', event)``     — another load is running, wait on the event
  - ``('skip', None)``      — warmup should skip (interactive already owns it)

Rules
~~~~~
- Warmup always **skips** if any load is in-flight (interactive or warmup).
  Reasoning: warmup is best-effort; retrying later is cheap.
- Interactive always **waits** if another load is in-flight (interactive or warmup).
  Reasoning: the user wants the result NOW; waiting for the existing load (even
  warmup) is faster than starting a duplicate.
"""

from __future__ import annotations

import threading
from typing import Dict, Optional, Tuple


class _InFlightEntry:
    __slots__ = ("event", "owner")

    def __init__(self, owner: str):
        self.event = threading.Event()
        self.owner = owner


class LoadCoordinator:
    """Thread-safe per-series load deduplication."""

    def __init__(self):
        self._lock = threading.Lock()
        self._inflight: Dict[str, _InFlightEntry] = {}

    # ------------------------------------------------------------------ API
    def try_acquire(
        self, series_number, owner: str = "interactive"
    ) -> Tuple[str, Optional[threading.Event]]:
        """Attempt to become the load-owner for *series_number*.

        Returns
        -------
        ('acquired', None)
            Caller should perform the load then call ``complete(series_number)``.
        ('wait', threading.Event)
            Another load is running.  Wait on the event, then check cache.
        ('skip', None)
            Warmup should skip — another load already in progress.
        """
        key = str(series_number)
        with self._lock:
            existing = self._inflight.get(key)
            if existing is not None:
                if owner == "warmup":
                    # Warmup always yields to any existing load.
                    return ("skip", None)
                # Interactive waits for existing load (warmup OR interactive).
                return ("wait", existing.event)

            entry = _InFlightEntry(owner)
            self._inflight[key] = entry
            return ("acquired", None)

    def complete(self, series_number):
        """Mark *series_number* load as done and unblock all waiters."""
        key = str(series_number)
        with self._lock:
            entry = self._inflight.pop(key, None)
        if entry is not None:
            entry.event.set()

    def is_loading(self, series_number) -> bool:
        with self._lock:
            return str(series_number) in self._inflight

    def cancel_all(self):
        """Unblock all waiters and clear state (e.g. on tab close)."""
        with self._lock:
            entries = list(self._inflight.values())
            self._inflight.clear()
        for entry in entries:
            entry.event.set()
