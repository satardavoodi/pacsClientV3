"""
tests/diagnostics/state_machine.py
=====================================
State machine reconstructor for the FAST viewer progressive display lifecycle.

Reconstructs a per-series viewer state machine from a sequence of EventEntry
objects and validates that only legal transitions occurred.

States (11)
-----------
  UNLOADED          — no series bound to this viewer slot
  LOADING           — series switch began, loader not yet bound
  STUB_BOUND        — pydicom_qt stub VTK created, backend binding done
  PROGRESSIVE_START — first grow batch available, progressive mode entered
  PROGRESSIVE_GROW  — receiving batch grows in-order
  PROGRESSIVE_STALE — grow returned fewer files than expected (OS flush lag)
  STALE_EXHAUSTED   — stale retry count reached max (5), fell back to loaded
  PROGRESSIVE_DONE  — final grow complete, progressive mode exited
  LOADED            — viewer showing series, not in progressive mode
  SWITCHING         — series switch started while another series was loaded
  CLOSED            — widget/tab was destroyed

Valid transitions
-----------------
See VALID_TRANSITIONS dict below.

Illegal transition detection
----------------------------
Any transition not in VALID_TRANSITIONS is recorded as an
ILLEGAL_TRANSITION in the reconstruction output.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from tests.diagnostics.event_log import (
    EventEntry,
    ET_SERIES_SWITCH_BEGIN,
    ET_SERIES_SWITCH_DONE,
    ET_BACKEND_BIND,
    ET_PROGRESSIVE_START,
    ET_PROGRESSIVE_GROW,
    ET_PROGRESSIVE_STALE,
    ET_PROGRESSIVE_STALE_EXHAUSTED,
    ET_PROGRESSIVE_COMPLETE,
    ET_PROGRESSIVE_MODE_ENTERED,
    ET_PROGRESSIVE_MODE_EXITED,
    ET_LOADER_BIND,
    ET_LOADER_RELEASED,
    ET_WIDGET_DESTROYED,
    ET_WIDGET_CREATED,
    ET_COMPLETION_VERIFY_DONE,
    ET_INFLIGHT_SET,
    ET_INFLIGHT_CLEARED,
    ET_DONE_GUARD_SET,
)

# ─── States ─────────────────────────────────────────────────────────────────

STATE_UNLOADED          = "UNLOADED"
STATE_LOADING           = "LOADING"
STATE_STUB_BOUND        = "STUB_BOUND"
STATE_PROGRESSIVE_START = "PROGRESSIVE_START"
STATE_PROGRESSIVE_GROW  = "PROGRESSIVE_GROW"
STATE_PROGRESSIVE_STALE = "PROGRESSIVE_STALE"
STATE_STALE_EXHAUSTED   = "STALE_EXHAUSTED"
STATE_PROGRESSIVE_DONE  = "PROGRESSIVE_DONE"
STATE_LOADED            = "LOADED"
STATE_SWITCHING         = "SWITCHING"
STATE_CLOSED            = "CLOSED"

ALL_STATES: FrozenSet[str] = frozenset({
    STATE_UNLOADED, STATE_LOADING, STATE_STUB_BOUND,
    STATE_PROGRESSIVE_START, STATE_PROGRESSIVE_GROW,
    STATE_PROGRESSIVE_STALE, STATE_STALE_EXHAUSTED,
    STATE_PROGRESSIVE_DONE, STATE_LOADED,
    STATE_SWITCHING, STATE_CLOSED,
})

VALID_TRANSITIONS: Dict[str, FrozenSet[str]] = {
    STATE_UNLOADED:          frozenset({STATE_LOADING, STATE_CLOSED}),
    STATE_LOADING:           frozenset({STATE_STUB_BOUND, STATE_LOADED, STATE_CLOSED}),
    STATE_STUB_BOUND:        frozenset({STATE_PROGRESSIVE_START, STATE_LOADED, STATE_SWITCHING, STATE_CLOSED}),
    STATE_PROGRESSIVE_START: frozenset({STATE_PROGRESSIVE_GROW, STATE_PROGRESSIVE_DONE, STATE_SWITCHING, STATE_CLOSED}),
    STATE_PROGRESSIVE_GROW:  frozenset({STATE_PROGRESSIVE_GROW, STATE_PROGRESSIVE_STALE, STATE_PROGRESSIVE_DONE, STATE_SWITCHING, STATE_CLOSED}),
    STATE_PROGRESSIVE_STALE: frozenset({STATE_PROGRESSIVE_GROW, STATE_PROGRESSIVE_STALE, STATE_STALE_EXHAUSTED, STATE_PROGRESSIVE_DONE, STATE_SWITCHING, STATE_CLOSED}),
    STATE_STALE_EXHAUSTED:   frozenset({STATE_LOADED, STATE_PROGRESSIVE_DONE, STATE_SWITCHING, STATE_CLOSED}),
    STATE_PROGRESSIVE_DONE:  frozenset({STATE_LOADED, STATE_SWITCHING, STATE_CLOSED}),
    STATE_LOADED:            frozenset({STATE_SWITCHING, STATE_LOADING, STATE_CLOSED}),
    STATE_SWITCHING:         frozenset({STATE_LOADING, STATE_STUB_BOUND, STATE_LOADED, STATE_CLOSED}),
    STATE_CLOSED:            frozenset(),
}


# ─── Reconstruction results ──────────────────────────────────────────────────

@dataclass
class StateTransition:
    seq: int
    ts: float
    from_state: str
    to_state: str
    event_type: str
    series_number: str
    fields: Dict[str, Any] = field(default_factory=dict)
    is_illegal: bool = False


@dataclass
class SeriesStateMachine:
    """Reconstructed state machine for one series_number."""
    series_number: str
    transitions: List[StateTransition] = field(default_factory=list)
    current_state: str = STATE_UNLOADED
    illegal_transitions: List[StateTransition] = field(default_factory=list)
    max_stale_depth: int = 0      # how many consecutive STALE states reached
    enter_count: int = 0          # how many times progressive mode was entered
    exit_count: int = 0           # how many times progressive mode was exited

    # Summary
    @property
    def has_illegal(self) -> bool:
        return bool(self.illegal_transitions)

    @property
    def completed_cleanly(self) -> bool:
        """True if final state is LOADED or PROGRESSIVE_DONE and no illegals."""
        return (
            self.current_state in (STATE_LOADED, STATE_PROGRESSIVE_DONE)
            and not self.has_illegal
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "series_number": self.series_number,
            "current_state": self.current_state,
            "completed_cleanly": self.completed_cleanly,
            "has_illegal_transitions": self.has_illegal,
            "illegal_count": len(self.illegal_transitions),
            "max_stale_depth": self.max_stale_depth,
            "enter_count": self.enter_count,
            "exit_count": self.exit_count,
            "transitions": [asdict(t) for t in self.transitions],
            "illegal_transitions": [asdict(t) for t in self.illegal_transitions],
        }


# ─── Event → state mapping ───────────────────────────────────────────────────

# Maps event_type → target state (for events that directly trigger transitions)
_EVENT_STATE_MAP: Dict[str, str] = {
    ET_SERIES_SWITCH_BEGIN:     STATE_SWITCHING,
    ET_BACKEND_BIND:            STATE_STUB_BOUND,
    ET_PROGRESSIVE_START:       STATE_PROGRESSIVE_START,
    ET_PROGRESSIVE_MODE_ENTERED: STATE_PROGRESSIVE_START,
    ET_PROGRESSIVE_GROW:        STATE_PROGRESSIVE_GROW,
    ET_PROGRESSIVE_STALE:       STATE_PROGRESSIVE_STALE,
    ET_PROGRESSIVE_STALE_EXHAUSTED: STATE_STALE_EXHAUSTED,
    ET_PROGRESSIVE_COMPLETE:    STATE_PROGRESSIVE_DONE,
    ET_PROGRESSIVE_MODE_EXITED: STATE_PROGRESSIVE_DONE,
    ET_LOADER_RELEASED:         STATE_LOADED,
    ET_WIDGET_DESTROYED:        STATE_CLOSED,
    ET_SERIES_SWITCH_DONE:      STATE_LOADING,
}


# ─── StateMachineReconstructor ────────────────────────────────────────────────

class StateMachineReconstructor:
    """Reconstruct per-series state machines from an event log.

    Parameters
    ----------
    default_series : str
        Fallback series_number when an event has no ``series_number`` field.
    """

    def __init__(self, default_series: str = "?") -> None:
        self._default = default_series
        self._machines: Dict[str, SeriesStateMachine] = {}
        self._stale_depth: Dict[str, int] = defaultdict(int)

    def feed(self, events: List[EventEntry]) -> None:
        """Process a list of events (may be called incrementally)."""
        for entry in events:
            sn = str(entry.fields.get("series_number", self._default))
            machine = self._get_or_create(sn)
            target = _EVENT_STATE_MAP.get(entry.event_type)
            if target is None:
                self._handle_special(machine, entry, sn)
                continue
            self._apply_transition(machine, entry, sn, target)

    def machines(self) -> Dict[str, SeriesStateMachine]:
        return dict(self._machines)

    def machine_for(self, series_number: str) -> Optional[SeriesStateMachine]:
        return self._machines.get(str(series_number))

    def summary(self) -> Dict[str, Any]:
        return {
            "total_series": len(self._machines),
            "clean_completions": sum(
                1 for m in self._machines.values() if m.completed_cleanly
            ),
            "illegal_transition_series": [
                sn for sn, m in self._machines.items() if m.has_illegal
            ],
            "max_stale_depth_any": max(
                (m.max_stale_depth for m in self._machines.values()), default=0
            ),
            "series_states": {
                sn: m.current_state for sn, m in self._machines.items()
            },
        }

    def write_json(self, path: Path | str) -> None:
        """Write all state machines to a JSON file."""
        data = {
            "summary": self.summary(),
            "machines": {
                sn: m.to_dict() for sn, m in self._machines.items()
            },
        }
        Path(path).write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    # ── internal ─────────────────────────────────────────────────────────────

    def _get_or_create(self, sn: str) -> SeriesStateMachine:
        if sn not in self._machines:
            self._machines[sn] = SeriesStateMachine(series_number=sn)
        return self._machines[sn]

    def _apply_transition(
        self,
        machine: SeriesStateMachine,
        entry: EventEntry,
        sn: str,
        to_state: str,
    ) -> None:
        from_state = machine.current_state
        is_legal = to_state in VALID_TRANSITIONS.get(from_state, frozenset())
        # Self-transitions (PROGRESSIVE_GROW → PROGRESSIVE_GROW) are always legal
        if from_state == to_state:
            is_legal = True

        # Track stale depth
        if to_state == STATE_PROGRESSIVE_STALE:
            self._stale_depth[sn] += 1
            machine.max_stale_depth = max(
                machine.max_stale_depth, self._stale_depth[sn]
            )
        elif to_state != STATE_PROGRESSIVE_STALE:
            self._stale_depth[sn] = 0

        # Track enter/exit counts
        if to_state == STATE_PROGRESSIVE_START:
            machine.enter_count += 1
        elif to_state in (STATE_PROGRESSIVE_DONE, STATE_LOADED) and from_state in (
            STATE_PROGRESSIVE_GROW, STATE_PROGRESSIVE_STALE, STATE_STALE_EXHAUSTED
        ):
            machine.exit_count += 1

        t = StateTransition(
            seq=entry.seq,
            ts=entry.ts,
            from_state=from_state,
            to_state=to_state,
            event_type=entry.event_type,
            series_number=sn,
            fields=dict(entry.fields),
            is_illegal=not is_legal,
        )
        machine.transitions.append(t)
        if not is_legal:
            machine.illegal_transitions.append(t)
        machine.current_state = to_state

    def _handle_special(
        self,
        machine: SeriesStateMachine,
        entry: EventEntry,
        sn: str,
    ) -> None:
        """Handle events that don't map directly to a state but affect context."""
        et = entry.event_type
        if et == ET_PROGRESSIVE_MODE_ENTERED:
            machine.enter_count += 1
        elif et == ET_PROGRESSIVE_MODE_EXITED:
            machine.exit_count += 1
