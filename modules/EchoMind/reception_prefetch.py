"""Fetch the reception record while the physician is dictating.

WHY THIS MOMENT. Recording and transcription are the one stretch of an EchoMind
session where the network is idle and nobody is waiting on us: the physician is
talking for anything from ten seconds to several minutes, and the report is not built
until they stop. Doing the reception fetch there means the service list is already in
the local cache by the time the report chat is minted — instead of the metadata card
showing "not detected" until somebody happens to open the reception tab.

WHAT IT IS FOR. The reception service is the strongest single input the region gate
will have. DICOM states laterality in 18% of studies here, and a body part alone
cannot tell *CT chest* from *CT angiography of the chest*; the booking can.

THE RULES THIS MODULE OBEYS, in order of importance:

1. **It can never affect the voice path.** Every entry point is swallowed, the work
   happens on a daemon thread, and the caller is not told to wait. A reception outage,
   a wrong URL, an unconfigured endpoint and a hung server must all look identical
   from the composer's point of view: nothing happened.
2. **It never blocks on a lock the UI holds**, and it never touches a widget. The UI
   re-reads the cache when transcription lands; this side only writes SQLite.
3. **It does not stampede.** One fetch per patient at a time, and none at all if the
   cache is younger than ``DEFAULT_MAX_AGE_S`` — a physician who re-records four times
   in a minute causes one request, not four.

The fetch itself is synchronous and lives in ``modules.network.reception_api_config``
so that the endpoint is defined in exactly one place; ``ReceptionDataFetchWorker`` in
the reception tab builds the same path, and a test asserts the two do not drift.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Set

logger = logging.getLogger(__name__)

#: How stale a cached service list may be before dictating again refetches it. A
#: booking can change during the working day (a service added at the desk after the
#: patient was scanned), but not minute to minute.
DEFAULT_MAX_AGE_S = 900

#: Short: this runs while someone is speaking, and a socket held open for 30 s past
#: the end of the dictation is a thread we are keeping alive for nothing.
FETCH_TIMEOUT_S = 8.0

_inflight: Set[str] = set()
_lock = threading.Lock()


def resolve_patient_id(study_uid: Optional[str]) -> Optional[str]:
    """The reception/patient id for a study, or None. Local SQLite only."""
    uid = (str(study_uid or "")).strip()
    if not uid:
        return None
    try:
        from PacsClient.utils import db_manager as db
        study = db.get_study_by_study_uid(uid) or None
        if not study:
            return None
        pk = study.get("patient_fk")
        if not pk:
            return None
        patient = db.get_patient_by_patient_pk(pk) or None
        pid = (str((patient or {}).get("patient_id") or "")).strip()
        return pid or None
    except Exception as exc:
        logger.debug("[EchoMind-prefetch] cannot resolve patient for %s: %s", uid, exc)
        return None


def cache_age_seconds(patient_id: str) -> Optional[float]:
    """Seconds since this patient's services were cached, or None if never."""
    try:
        from PacsClient.utils import ai_get_reception_services_updated_at
        ts = ai_get_reception_services_updated_at(patient_id)
    except Exception as exc:
        logger.debug("[EchoMind-prefetch] cache age unavailable: %s", exc)
        return None
    if not ts:
        return None
    return max(0.0, time.time() - float(ts))


def is_fresh(patient_id: str, max_age_s: float = DEFAULT_MAX_AGE_S) -> bool:
    age = cache_age_seconds(patient_id)
    return age is not None and age < max_age_s


def fetch_and_cache(patient_id: str, *, study_uid: Optional[str] = None) -> int:
    """Fetch this patient's reception record and cache its services. Synchronous.

    Returns how many services were stored; 0 means "we learned nothing", which is a
    normal outcome and not an error. Never raises.
    """
    pid = (str(patient_id or "")).strip()
    if not pid:
        return 0
    try:
        from modules.network.reception_api_config import fetch_patient_record
        record = fetch_patient_record(pid, timeout=FETCH_TIMEOUT_S)
    except Exception as exc:
        logger.debug("[EchoMind-prefetch] fetch failed for %s: %s", pid, exc)
        return 0
    if not isinstance(record, dict):
        return 0

    services = record.get("services") or []
    if not services:
        # A real answer: this patient has no services on file. Do NOT write an empty
        # list — the cache treats an empty write as "no news" precisely so a bad
        # response cannot erase a good one.
        logger.debug("[EchoMind-prefetch] %s: reception returned no services", pid)
        return 0

    try:
        from PacsClient.utils import ai_save_reception_services
        n = ai_save_reception_services(
            pid, services,
            study_uid=(study_uid or record.get("studyUID") or record.get("study_uid")),
        )
    except Exception as exc:
        logger.warning("[EchoMind-prefetch] could not cache services for %s: %s", pid, exc)
        return 0
    logger.info("[EchoMind-prefetch] cached %d reception service(s) for %s", n, pid)
    return n


def prefetch(
    *,
    study_uid: Optional[str] = None,
    patient_id: Optional[str] = None,
    max_age_s: float = DEFAULT_MAX_AGE_S,
    blocking: bool = False,
) -> bool:
    """Warm the reception cache for this study. Returns True if a fetch was started.

    Called from the composer the moment recording begins, and again when a
    transcription starts (which covers an audio file dropped in without recording).
    Returns False — silently, and this is the common case — when the patient cannot be
    resolved, the cache is still fresh, or a fetch for the same patient is already
    running.

    ``blocking`` exists for tests. Production callers must never set it: the composer
    calls this on the UI thread while starting an audio stream.
    """
    try:
        pid = (str(patient_id or "")).strip() or resolve_patient_id(study_uid)
        if not pid:
            return False
        if is_fresh(pid, max_age_s):
            logger.debug("[EchoMind-prefetch] %s: cache is fresh, skipping", pid)
            return False

        with _lock:
            if pid in _inflight:
                logger.debug("[EchoMind-prefetch] %s: already in flight", pid)
                return False
            _inflight.add(pid)

        def _run():
            try:
                fetch_and_cache(pid, study_uid=study_uid)
            finally:
                with _lock:
                    _inflight.discard(pid)

        if blocking:
            _run()
            return True

        # daemon: a reception server that never answers must not keep the workstation
        # alive at shutdown.
        threading.Thread(
            target=_run, name=f"echomind-reception-prefetch-{pid}", daemon=True
        ).start()
        return True
    except Exception as exc:                        # pragma: no cover - defensive
        logger.debug("[EchoMind-prefetch] not started: %s", exc)
        return False
