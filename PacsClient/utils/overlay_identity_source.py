"""Reads patient/study IDENTITY tags from the DISPLAYED series' own DICOM header.

This is the adapter that lets the viewport overlay reflect the DICOM image
currently on screen — the fix for the clinical-safety defect where the overlay
showed a patient/study-level DB row keyed by ``patient_id`` instead of the
image's own tags. Because ``patients.patient_id`` is UNIQUE, two different
people accidentally sent under one Patient ID collapse to a single DB row, so
the DB-sourced overlay painted the SAME name on both patients' images. Reading
the tags straight from the series' first instance makes the overlay match the
pixels, whatever the DB says.

WHERE THIS SITS IN THE ARCHITECTURE
-----------------------------------
The pure ``overlay_metadata`` trunk (stdlib only, no pydicom) decides the final
overlay TEXT from whatever sources it is handed. THIS module is the small
pydicom adapter that produces the ``dicom=`` source for that trunk — the image
tags. Both the FAST and the Advanced viewers call this ONE reader and then the
ONE trunk, so they render identical text for the same series without either
domain reaching into the other (they unify only through this read-only trunk
pair, never across a domain boundary).

SCOPE: descriptive IDENTITY text only — PatientName/ID/Sex/Age, StudyDate/Time,
InstitutionName, and the per-series descriptive fields. It does NOT read or
decide series identity (SeriesInstanceUID / series number / offset keys),
geometry, slice order, or the slice counter — those are owned downstream and
must never be sourced from here.

PERFORMANCE
-----------
The overlay repaints on every slice scroll and window/level change, so this
must never do disk I/O on the paint path. The read happens ONCE per series and
is cached, keyed by ``(path, mtime)``. The ``mtime`` component means a file
rewritten in place by the demographic-tag editor is re-read with its corrected
values rather than served a stale cache entry. Reads are ``stop_before_pixels``
and limited to the identity tags, so each is a few-KB header parse.

Never raises: a failed read returns ``{}`` and the trunk simply falls back to
its next source (the DB), which is exactly the pre-existing behaviour — the
overlay must never break because a header could not be parsed.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Dict

logger = logging.getLogger(__name__)

#: overlay-model key -> DICOM keyword. These are the identity/descriptive tags
#: that were previously sourced from the DB patient/study row. Rows/Columns
#: (image dimensions) are deliberately NOT here — those already come correctly
#: from the per-instance header stub and are per-slice, not series-constant.
_IDENTITY_TAGS: Dict[str, str] = {
    "patient_name": "PatientName",
    "patient_id": "PatientID",
    "patient_sex": "PatientSex",
    "patient_age": "PatientAge",
    "study_date": "StudyDate",
    "study_time": "StudyTime",
    "institution_name": "InstitutionName",
    "series_description": "SeriesDescription",
    "modality": "Modality",
}

_cache: Dict[str, tuple] = {}          # path -> (mtime, result_dict)
_cache_lock = threading.Lock()
_CACHE_MAX = 512


def clear_cache() -> None:
    """Drop all cached reads (e.g. after a bulk on-disk edit)."""
    with _cache_lock:
        _cache.clear()


def read_identity_tags(first_instance_path) -> Dict[str, str]:
    """Identity tags from ONE DICOM file (a series' first instance).

    Returns a dict of overlay-model keys to trimmed string values. A tag absent
    from the file maps to ``""`` (which the trunk treats as missing, so a lower-
    precedence source can supply it). Returns ``{}`` when the path is empty or
    unreadable. Cached by ``(path, mtime)``; never raises.
    """
    path = str(first_instance_path or "").strip()
    if not path:
        return {}

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0

    with _cache_lock:
        cached = _cache.get(path)
    if cached is not None and cached[0] == mtime:
        return dict(cached[1])

    result: Dict[str, str] = {}
    try:
        import pydicom

        ds = pydicom.dcmread(
            path,
            stop_before_pixels=True,
            force=True,
            specific_tags=list(_IDENTITY_TAGS.values()),
        )
        for key, keyword in _IDENTITY_TAGS.items():
            value = getattr(ds, keyword, None)
            result[key] = "" if value is None else str(value).strip()
    except Exception:
        logger.debug(
            "[OVERLAY-IDENTITY] header read failed for %s", path, exc_info=True
        )
        result = {}

    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[path] = (mtime, dict(result))
    return dict(result)


def read_series_identity_from_instances(instances) -> Dict[str, str]:
    """Convenience: read identity tags from the FIRST instance of a metadata
    ``instances`` list (the shape both viewers already hold).

    Identity tags are series-constant by DICOM definition, so the first
    instance represents the whole series and is read once. Returns ``{}`` when
    there is no usable instance path — the caller then falls back to the DB.
    """
    if not instances:
        return {}
    try:
        first = instances[0]
        path = first.get("instance_path", "") if isinstance(first, dict) else ""
    except Exception:
        path = ""
    return read_identity_tags(path)
