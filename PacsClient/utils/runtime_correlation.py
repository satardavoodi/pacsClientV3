"""Runtime event correlation helpers for instrumentation-only diagnostics.

This module is intentionally lightweight and side-effect free. It provides a
shared monotonic timeline buffer so independent subsystems can stamp events
with a common session id and query nearby prior events.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections import deque
from typing import Any, Dict, Iterable, Optional

_MAX_EVENTS = 8000
_LOCK = threading.Lock()
_EVENTS = deque(maxlen=_MAX_EVENTS)
_EVENT_COUNTER = 0

_SESSION_ID = os.environ.get("AIPACS_CORR_SESSION_ID", "").strip() or f"sess-{uuid.uuid4().hex[:12]}"

_ACTIVE_STATE: Dict[str, Any] = {
    "viewer_state": "unknown",
    "series_uid": "",
    "series_number": "",
    "interaction_active": False,
    "updated_mono_ms": 0.0,
}


def now_mono_ms() -> float:
    return time.perf_counter() * 1000.0


def session_id() -> str:
    return _SESSION_ID


def set_active_viewer_state(
    *,
    viewer_state: Optional[str] = None,
    series_uid: Optional[str] = None,
    series_number: Optional[str] = None,
    interaction_active: Optional[bool] = None,
) -> None:
    now_ms = now_mono_ms()
    with _LOCK:
        if viewer_state is not None:
            _ACTIVE_STATE["viewer_state"] = str(viewer_state)
        if series_uid is not None:
            _ACTIVE_STATE["series_uid"] = str(series_uid)
        if series_number is not None:
            _ACTIVE_STATE["series_number"] = str(series_number)
        if interaction_active is not None:
            _ACTIVE_STATE["interaction_active"] = bool(interaction_active)
        _ACTIVE_STATE["updated_mono_ms"] = now_ms


def get_active_viewer_state() -> Dict[str, Any]:
    with _LOCK:
        return dict(_ACTIVE_STATE)


def record_event(category: str, **fields: Any) -> Dict[str, Any]:
    global _EVENT_COUNTER
    now_ms = now_mono_ms()
    with _LOCK:
        _EVENT_COUNTER += 1
        event = {
            "event_id": int(_EVENT_COUNTER),
            "session_id": _SESSION_ID,
            "mono_ms": float(now_ms),
            "category": str(category),
            "fields": dict(fields),
        }
        _EVENTS.append(event)
    return dict(event)


def _match_fields(event: Dict[str, Any], match: Optional[Dict[str, Any]]) -> bool:
    if not match:
        return True
    fields = event.get("fields", {})
    for key, val in match.items():
        if fields.get(key) != val:
            return False
    return True


def nearest_previous(
    categories: Iterable[str],
    *,
    now_ms: Optional[float] = None,
    within_ms: float = 1000.0,
    match: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    target_ms = float(now_mono_ms() if now_ms is None else now_ms)
    cats = set(str(c) for c in categories)
    with _LOCK:
        for event in reversed(_EVENTS):
            if event.get("category") not in cats:
                continue
            age = target_ms - float(event.get("mono_ms", 0.0))
            if age < 0.0:
                continue
            if age > float(within_ms):
                return None
            if not _match_fields(event, match):
                continue
            return dict(event)
    return None


def count_events_between(category: str, start_ms: float, end_ms: float) -> int:
    start_v = float(start_ms)
    end_v = float(end_ms)
    with _LOCK:
        total = 0
        for event in _EVENTS:
            if event.get("category") != str(category):
                continue
            ts = float(event.get("mono_ms", 0.0))
            if start_v <= ts <= end_v:
                total += 1
        return total


def format_near_event(event: Optional[Dict[str, Any]], *, now_ms: Optional[float] = None) -> str:
    if not event:
        return "none"
    target_ms = float(now_mono_ms() if now_ms is None else now_ms)
    ts = float(event.get("mono_ms", 0.0))
    age = max(0.0, target_ms - ts)
    category = str(event.get("category", "?"))
    event_id = int(event.get("event_id", 0))
    return f"{category}#{event_id}@{age:.1f}ms"


def find_recent_event(
    category: str,
    *,
    match: Optional[Dict[str, Any]] = None,
    within_ms: float = 5000.0,
    now_ms: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    return nearest_previous(
        [str(category)],
        now_ms=now_ms,
        within_ms=within_ms,
        match=match,
    )
