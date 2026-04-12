"""
tests/diagnostics/event_log.py
================================
Crash-safe, thread-safe append-only event log for the FAST viewer diagnostic
framework.

Architecture
------------
- All events are appended to an in-memory deque AND flushed to ``events.jsonl``
  via ``os.write`` (bypass Python buffering) so that every event is durable
  immediately even if the process is killed.
- A rolling ring buffer (last ``RING_BUFFER_SIZE`` events) is kept for fast
  replay without re-reading the full log.
- ``EventLog.flush_ring_buffer()`` atomically writes ``ring_buffer.json``.
- The file handle is opened once at construction time; ``close()`` must be
  called (or use as context manager) to flush OS buffers and close the fd.

Event types
-----------
All EVENT_TYPE_* constants are defined here.  Add new ones as needed; each
should be a short ``UPPER_SNAKE`` string unique across the codebase.
"""
from __future__ import annotations

import collections
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

# ─── Event type registry ─────────────────────────────────────────────────────

# Progressive display lifecycle
ET_PROGRESSIVE_START            = "PROGRESSIVE_START"
ET_PROGRESSIVE_GROW             = "PROGRESSIVE_GROW"
ET_PROGRESSIVE_STALE            = "PROGRESSIVE_STALE"
ET_PROGRESSIVE_STALE_EXHAUSTED  = "PROGRESSIVE_STALE_EXHAUSTED"
ET_PROGRESSIVE_COMPLETE         = "PROGRESSIVE_COMPLETE"
ET_PROGRESSIVE_MODE_ENTERED     = "PROGRESSIVE_MODE_ENTERED"
ET_PROGRESSIVE_MODE_EXITED      = "PROGRESSIVE_MODE_EXITED"

# Download signals
ET_SERIES_PROGRESS              = "SERIES_PROGRESS"
ET_SERIES_DOWNLOAD_COMPLETE     = "SERIES_DOWNLOAD_COMPLETE"
ET_COMPLETION_PULSE             = "COMPLETION_PULSE"

# Lazy loader lifecycle
ET_LOADER_CREATED               = "LOADER_CREATED"
ET_LOADER_REGISTERED            = "LOADER_REGISTERED"
ET_LOADER_RELEASED              = "LOADER_RELEASED"
ET_LOADER_BIND                  = "LOADER_BIND"
ET_LOADER_UNBIND                = "LOADER_UNBIND"
ET_DECODE_SLICE_READY           = "DECODE_SLICE_READY"
ET_DECODE_FAILED                = "DECODE_FAILED"
ET_GROW_CALLED                  = "GROW_CALLED"
ET_GROW_RETURNED                = "GROW_RETURNED"

# Backend / series switch
ET_SERIES_SWITCH_BEGIN          = "SERIES_SWITCH_BEGIN"
ET_SERIES_SWITCH_DONE           = "SERIES_SWITCH_DONE"
ET_BACKEND_BIND                 = "BACKEND_BIND"
ET_GENERATION_INCR              = "GENERATION_INCR"

# Metadata / geometry
ET_METADATA_REFRESH_BEGIN       = "METADATA_REFRESH_BEGIN"
ET_METADATA_REFRESH_DONE        = "METADATA_REFRESH_DONE"

# Tab / widget lifecycle
ET_WIDGET_CREATED               = "WIDGET_CREATED"
ET_WIDGET_DESTROYED             = "WIDGET_DESTROYED"
ET_TAB_OPENED                   = "TAB_OPENED"
ET_TAB_CLOSED                   = "TAB_CLOSED"

# Completion layers
ET_COMPLETION_VERIFY_START      = "COMPLETION_VERIFY_START"
ET_COMPLETION_VERIFY_DONE       = "COMPLETION_VERIFY_DONE"
ET_COMPLETION_SWEEP_TICK        = "COMPLETION_SWEEP_TICK"

# Inflight / done-guard
ET_INFLIGHT_SET                 = "INFLIGHT_SET"
ET_INFLIGHT_CLEARED             = "INFLIGHT_CLEARED"
ET_DONE_GUARD_SET               = "DONE_GUARD_SET"
ET_DONE_GUARD_RECOVERY          = "DONE_GUARD_RECOVERY"

# Error / exception
ET_EXCEPTION_SWALLOWED          = "EXCEPTION_SWALLOWED"
ET_EXCEPTION_PROPAGATED         = "EXCEPTION_PROPAGATED"

# Memory / resource
ET_MEMORY_SNAPSHOT              = "MEMORY_SNAPSHOT"
ET_GC_COLLECT                   = "GC_COLLECT"

# Scenario control
ET_SCENARIO_BEGIN               = "SCENARIO_BEGIN"
ET_SCENARIO_STEP                = "SCENARIO_STEP"
ET_SCENARIO_END                 = "SCENARIO_END"
ET_LAST_GOOD_STATE              = "LAST_GOOD_STATE"

# All registered event types (for validation in replays)
ALL_EVENT_TYPES: frozenset = frozenset({
    v for k, v in globals().items() if k.startswith("ET_")
})

RING_BUFFER_SIZE = 200


# ─── EventEntry dataclass ─────────────────────────────────────────────────────

@dataclass
class EventEntry:
    """One event in the diagnostic log."""
    ts: float               # time.monotonic() — relative to process start
    wall_ts: float          # time.time()       — absolute UTC epoch seconds
    event_type: str
    thread_name: str
    seq: int                # monotonically increasing sequence number
    fields: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "wall_ts": self.wall_ts,
            "event_type": self.event_type,
            "thread_name": self.thread_name,
            "seq": self.seq,
            **self.fields,
        }

    def to_jsonl_line(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False) + "\n"


# ─── EventLog ────────────────────────────────────────────────────────────────

class EventLog:
    """Thread-safe, crash-safe, append-only diagnostic event log.

    Parameters
    ----------
    output_dir : Path | str | None
        Directory where ``events.jsonl`` will be written.  If *None*, the log
        operates in memory-only mode (no disk I/O).
    ring_buffer_size : int
        Maximum number of events kept in the rolling ring buffer.
    """

    def __init__(
        self,
        output_dir: Optional[Path | str] = None,
        ring_buffer_size: int = RING_BUFFER_SIZE,
    ) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._t0 = time.monotonic()
        self._ring: Deque[EventEntry] = collections.deque(maxlen=ring_buffer_size)
        self._all: List[EventEntry] = []          # full in-memory log
        self._fd: Optional[int] = None            # raw OS file descriptor
        self._output_dir: Optional[Path] = None
        self._closed = False

        if output_dir is not None:
            p = Path(output_dir)
            p.mkdir(parents=True, exist_ok=True)
            self._output_dir = p
            events_path = p / "events.jsonl"
            # Open in append-binary mode; bypass Python buffering
            self._fd = os.open(
                str(events_path),
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o644,
            )

    # ── core API ─────────────────────────────────────────────────────────────

    def append(
        self,
        event_type: str,
        **fields: Any,
    ) -> EventEntry:
        """Record one event.  Thread-safe; never raises."""
        try:
            now_mono = time.monotonic() - self._t0
            now_wall = time.time()
            tname = threading.current_thread().name

            with self._lock:
                if self._closed:
                    return _DEAD_ENTRY
                seq = self._seq
                self._seq += 1
                entry = EventEntry(
                    ts=now_mono,
                    wall_ts=now_wall,
                    event_type=event_type,
                    thread_name=tname,
                    seq=seq,
                    fields=fields,
                )
                self._ring.append(entry)
                self._all.append(entry)

            # Write to disk outside lock (os.write is atomic for short writes on POSIX;
            # on Windows we accept the race — crash-safety here is best-effort)
            if self._fd is not None:
                line = entry.to_jsonl_line().encode("utf-8")
                try:
                    os.write(self._fd, line)
                except OSError:
                    pass  # disk full / fd closed — don't block the caller

            return entry
        except Exception:
            # Never let logging crash the app
            return _DEAD_ENTRY

    def events(self) -> List[EventEntry]:
        """Return a snapshot of all recorded events."""
        with self._lock:
            return list(self._all)

    def ring_buffer(self) -> List[EventEntry]:
        """Return a snapshot of the rolling ring buffer."""
        with self._lock:
            return list(self._ring)

    def events_of_type(self, *event_types: str) -> List[EventEntry]:
        with self._lock:
            et_set = set(event_types)
            return [e for e in self._all if e.event_type in et_set]

    def count(self, event_type: str) -> int:
        with self._lock:
            return sum(1 for e in self._all if e.event_type == event_type)

    def since_seq(self, seq: int) -> List[EventEntry]:
        """Return all events with seq >= seq."""
        with self._lock:
            return [e for e in self._all if e.seq >= seq]

    def flush_ring_buffer(self) -> None:
        """Atomically write ring_buffer.json (overwrite)."""
        if self._output_dir is None:
            return
        try:
            entries = self.ring_buffer()
            data = [e.to_dict() for e in entries]
            tmp = self._output_dir / "ring_buffer.tmp"
            dst = self._output_dir / "ring_buffer.json"
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(dst)
        except Exception:
            pass

    def flush_last_good_state(self, state: Dict[str, Any]) -> None:
        """Atomically write last_good_state.json — called every 60 s in real-run mode."""
        if self._output_dir is None:
            return
        try:
            state["_snapshot_ts"] = time.time()
            tmp = self._output_dir / "last_good_state.tmp"
            dst = self._output_dir / "last_good_state.json"
            tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            tmp.replace(dst)
        except Exception:
            pass

    def close(self) -> None:
        """Flush and close the underlying file descriptor."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def __enter__(self) -> "EventLog":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def __len__(self) -> int:
        with self._lock:
            return len(self._all)

    def __repr__(self) -> str:
        return f"<EventLog seq={self._seq} output={self._output_dir}>"


# Sentinel returned when the log is closed or encounters an error
_DEAD_ENTRY = EventEntry(
    ts=0.0, wall_ts=0.0,
    event_type="<dead>",
    thread_name="<dead>",
    seq=-1,
)


# ─── load_from_jsonl (replay mode) ───────────────────────────────────────────

def load_from_jsonl(path: Path | str) -> List[EventEntry]:
    """Load events from a saved events.jsonl file for replay analysis."""
    entries: List[EventEntry] = []
    with open(str(path), "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
                fields = {
                    k: v for k, v in data.items()
                    if k not in ("ts", "wall_ts", "event_type", "thread_name", "seq")
                }
                entries.append(EventEntry(
                    ts=float(data.get("ts", 0)),
                    wall_ts=float(data.get("wall_ts", 0)),
                    event_type=str(data.get("event_type", "UNKNOWN")),
                    thread_name=str(data.get("thread_name", "")),
                    seq=int(data.get("seq", lineno)),
                    fields=fields,
                ))
            except (json.JSONDecodeError, KeyError, ValueError):
                pass  # skip corrupt lines
    return entries
