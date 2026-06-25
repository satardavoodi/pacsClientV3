"""Local-only physician reminders: pin / alarm / private note (2026-06-06).

Stored ONLY on this workstation — never sent to or synchronized with the
PACS / reception / reporting server. Backs the "Local Physician Reminder"
section of the Report popup and the pin/alarm/note indicators in the
home-page patient list.

Storage: ``USER_DATA_ROOT/config/local_physician_reminders.json``
    { "<patient_id>": {
          "pinned": bool, "alarm": bool, "note": str,
          "study_uid": str,        # last study the reminder was edited from
          "updated_at": iso-8601 } }

Keying: the PATIENT ID (trimmed string) — the pin/alarm follow the patient
across studies in future searches, which is the clinical intent; the study
UID is recorded for context. Reads are cached in memory; writes are atomic
(tmp + os.replace) and guarded by a lock.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CACHE: dict | None = None

_FIELDS = ("pinned", "alarm", "note")


def _store_path() -> Path:
    from PacsClient.utils.data_paths import USER_DATA_ROOT
    return Path(USER_DATA_ROOT) / "config" / "local_physician_reminders.json"


def _normalize_key(patient_id) -> str:
    return str(patient_id or "").strip()


def _load_unlocked() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = _store_path()
    data: dict = {}
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                data = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    except Exception:
        logger.warning("[local-reminders] failed to read store; starting empty", exc_info=True)
        data = {}
    _CACHE = data
    return data


def _save_unlocked(data: dict) -> bool:
    path = _store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        logger.warning("[local-reminders] failed to write store", exc_info=True)
        return False


def get_reminder(patient_id) -> dict:
    """Return {'pinned','alarm','note','study_uid','updated_at'} (defaults when absent)."""
    key = _normalize_key(patient_id)
    base = {"pinned": False, "alarm": False, "note": "", "study_uid": "", "updated_at": ""}
    if not key:
        return base
    with _LOCK:
        entry = _load_unlocked().get(key)
        if isinstance(entry, dict):
            out = dict(base)
            out["pinned"] = bool(entry.get("pinned", False))
            out["alarm"] = bool(entry.get("alarm", False))
            out["note"] = str(entry.get("note", "") or "")
            out["study_uid"] = str(entry.get("study_uid", "") or "")
            out["updated_at"] = str(entry.get("updated_at", "") or "")
            return out
    return base


def set_reminder(patient_id, *, pinned=None, alarm=None, note=None, study_uid="", row=None) -> bool:
    """Merge-update a patient's local reminder. Local file only — no server I/O.

    ``row`` (optional) is a snapshot of the patient's Main-Page list-row fields,
    persisted so a PINNED patient can be rendered as a search-list overlay even
    when the current query would not return them (and across app restarts). It
    is stored only as context; it never changes the pin/alarm/note state.

    Entries that end up all-default (no pin, no alarm, empty note) are
    removed from the store to keep it tidy (the row snapshot goes with them).
    """
    key = _normalize_key(patient_id)
    if not key:
        return False
    with _LOCK:
        data = _load_unlocked()
        entry = dict(data.get(key) or {})
        if pinned is not None:
            entry["pinned"] = bool(pinned)
        if alarm is not None:
            entry["alarm"] = bool(alarm)
        if note is not None:
            entry["note"] = str(note)
        if study_uid:
            entry["study_uid"] = str(study_uid)
        if isinstance(row, dict) and row:
            entry["row"] = dict(row)
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")

        if not entry.get("pinned") and not entry.get("alarm") and not str(entry.get("note", "")).strip():
            data.pop(key, None)
        else:
            data[key] = entry
        return _save_unlocked(data)


def get_pinned_rows() -> dict:
    """Return ``{patient_id: row_snapshot}`` for every PINNED patient that has a
    stored row snapshot — the persistent source for the Main-Page search-list
    "pinned overlay". Local only; survives app restart (read from the JSON
    store). Patients pinned without a snapshot are omitted (nothing to render).
    """
    out: dict = {}
    with _LOCK:
        data = _load_unlocked()
        for k, v in data.items():
            if isinstance(v, dict) and v.get("pinned") and isinstance(v.get("row"), dict) and v.get("row"):
                out[str(k)] = dict(v["row"])
    return out


def get_pinned_patient_ids() -> set:
    """Return the set of ALL pinned patient_ids (regardless of whether a row
    snapshot exists). The Main-Page list uses this to know which currently-shown
    rows must be floated to the pinned/top section. Local only."""
    out = set()
    with _LOCK:
        for k, v in _load_unlocked().items():
            if isinstance(v, dict) and v.get("pinned"):
                out.add(str(k))
    return out


def has_flags(patient_id) -> bool:
    """True when the patient has any local pin/alarm/note set."""
    r = get_reminder(patient_id)
    return bool(r["pinned"] or r["alarm"] or str(r["note"]).strip())


def reset_cache_for_tests() -> None:
    """Test hook: drop the in-memory cache (storage path may be monkeypatched)."""
    global _CACHE
    with _LOCK:
        _CACHE = None
