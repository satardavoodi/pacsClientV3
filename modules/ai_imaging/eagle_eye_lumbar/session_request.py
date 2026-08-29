"""Hand a resolved Eagle Eye run from the button to the tab it opens.

The resolution is worked out in the patient tab (that is where the user is when
they click), but it is consumed in the Eagle Eye tab, which is a different
widget built moments later by ``method_add_new_tab``. That call already threads
``study_uid`` and ``eagle_eye_mode`` through several layers; adding a fourth
parameter would mean touching every one of them.

So the request is parked here and collected by study UID. Two properties keep
that honest rather than sloppy global state:

  * ``take`` REMOVES the request, so it can be consumed exactly once and a
    stale resolution can never be picked up by a later, unrelated run;
  * requests carry a timestamp and expire, so an abandoned one (the tab failed
    to open) cannot be collected minutes later by a different study.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# A resolution older than this is treated as abandoned. Generous enough for a
# slow tab build, far short of "the user did something else and came back".
_TTL_SECONDS = 180.0

_lock = threading.Lock()
_pending: Dict[str, Dict[str, Any]] = {}

_PATIENT_ID_KEYS = (
    "patient_id",
    "patientID",
    "PatientID",
    "patient_code",
    "PatientCode",
)


def _patient_id_for_widget(patient_widget: Any) -> str:
    patient_id = getattr(patient_widget, "patient_id", None)
    metadata = getattr(patient_widget, "metadata_fixed", {}) or {}
    if not patient_id and isinstance(metadata, dict):
        for key in _PATIENT_ID_KEYS:
            if metadata.get(key):
                patient_id = metadata[key]
                break
    return str(patient_id or "").strip()


def with_study_context(
    payload: Dict[str, Any],
    patient_widget: Any,
    selection: Any,
    candidates: Any = None,
) -> Dict[str, Any]:
    """Attach the original patient tab's bounded context to a handoff copy."""
    from .series_context import snapshot_series_catalog

    inventory_scope, inventory = snapshot_series_catalog(
        patient_widget,
        selection,
        candidates=candidates,
    )
    enriched = dict(payload or {})
    enriched["study_context"] = {
        "patient_id": _patient_id_for_widget(patient_widget),
        "study_series_inventory_scope": inventory_scope,
        "study_series_inventory": inventory,
    }
    return enriched


def stash(study_uid: str, payload: Dict[str, Any]) -> None:
    """Park a resolved request for the Eagle Eye tab that is about to open."""
    key = str(study_uid or "").strip()
    if not key:
        logger.warning("eagle_eye: refusing to stash a request with no study UID")
        return
    with _lock:
        _prune_locked()
        _pending[key] = {"payload": dict(payload or {}), "stashed_at": time.monotonic()}
    logger.info("eagle_eye: resolution stashed for study %s", key)


def take(study_uid: str) -> Optional[Dict[str, Any]]:
    """Collect and REMOVE the request for ``study_uid``, if one is waiting."""
    key = str(study_uid or "").strip()
    if not key:
        return None
    with _lock:
        _prune_locked()
        entry = _pending.pop(key, None)
    if entry is None:
        return None
    return entry["payload"]


def peek(study_uid: str) -> Optional[Dict[str, Any]]:
    """Look without consuming - for logging and tests only."""
    key = str(study_uid or "").strip()
    with _lock:
        _prune_locked()
        entry = _pending.get(key)
    return dict(entry["payload"]) if entry else None


def clear() -> None:
    with _lock:
        _pending.clear()


def _prune_locked() -> None:
    now = time.monotonic()
    for key in [k for k, v in _pending.items() if now - v["stashed_at"] > _TTL_SECONDS]:
        logger.info("eagle_eye: discarding abandoned resolution for study %s", key)
        _pending.pop(key, None)
