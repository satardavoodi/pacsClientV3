"""Series-identity normalization — the ONE authority for server-provided series numbers.

Why this exists (root cause, 2026-07-12, Roshana center)
--------------------------------------------------------
A radiography (DX/CR) device wrote DICOM without a usable ``SeriesNumber``
(0020,0011). The PACS server serialized that missing value as the **literal
string** ``"None"`` in its ``GetStudyThumbnails`` socket payload. Every client
site that treated the value as "a number, or falsy" then broke, because
``"None"`` is a *truthy non-empty string*:

    int(str(series.get("series_number") or 0))   # -> int("None") -> ValueError

That ``ValueError`` escaped the download manager's metadata builder, so the
**whole study's** metadata fetch failed (3 retries, then "Failed to fetch
metadata"), the download never started, and the images could never be
displayed. A single cosmetic missing tag took down an entire study.

The rule
--------
``SeriesNumber`` is **optional** in the DICOM standard (type 2 / may be empty).
Any device, at any center, may omit it. So we never trust it to be a number and
we never let a bad one reach application code:

    Normalize ONCE, at the socket ingestion boundary, so that no consumer
    (download manager, database, thumbnails, viewer, previous-exams) ever sees
    a non-numeric series number.

Design guarantees
-----------------
1. **Byte-identical for good data.** A series whose number already parses as a
   number is left *completely untouched* — same object, same value, same type
   (``"01"`` stays the string ``"01"``). Only unusable entries are rewritten.
   Every center with conformant devices therefore behaves exactly as before.

2. **Non-colliding synthetic numbers.** A missing number is replaced with one
   from the reserved band ``900001..999999`` — above any plausible real
   ``SeriesNumber``, and strictly below ``1_000_000``, which is the multi-study
   *offset-key* threshold (``study_slot * 1_000_000 + series_number``). A
   synthetic number can therefore never be mistaken for an offset key, and can
   never collide with a real series of the same study (real numbers already
   present are excluded from the band).

3. **Deterministic.** Synthetic numbers are assigned in ``series_uid`` order,
   not server-list order, so the same series gets the same number on every
   fetch, in every process (UI *and* download subprocess) — which is what keeps
   the on-disk folder ``SOURCE_PATH/<study_uid>/<series_number>/``, the
   thumbnail ``<series_number>.png`` and the DB row in agreement across
   sessions.

4. **Pure stdlib.** No Qt / pydicom / numpy / network imports — unit-testable in
   isolation and importable from the download subprocess.

Kill switch: ``AIPACS_SERIES_NUMBER_NORMALIZE=0`` restores the byte-identical
legacy behaviour (raw server value passed straight through).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "SYNTHETIC_SERIES_NUMBER_BASE",
    "SYNTHETIC_SERIES_NUMBER_MAX",
    "is_normalize_enabled",
    "parse_series_number",
    "normalize_series_entries",
]


# Reserved synthetic band. Chosen so that:
#   * it is far above any real DICOM SeriesNumber (devices use 1..9999), and
#   * it stays BELOW 1_000_000, the multi-study offset-key threshold
#     (see _vc_cache.py: `int(str(series_number)) >= 1_000_000` == offset key).
SYNTHETIC_SERIES_NUMBER_BASE = 900_000
SYNTHETIC_SERIES_NUMBER_MAX = 999_999

# Values a server may send for "this tag was absent/empty". The string "None"
# is the one that caused the outage (Python `str(None)` leaking into the wire
# format); the rest are the usual suspects across PACS implementations.
_MISSING_TOKENS = {
    "",
    "none",
    "null",
    "nil",
    "nan",
    "n/a",
    "na",
    "-",
    "--",
    "unknown",
    "undefined",
}

_SERIES_LIST_KEYS = ("series_thumbnails", "series")


def is_normalize_enabled() -> bool:
    """Default ON. ``AIPACS_SERIES_NUMBER_NORMALIZE=0`` = legacy passthrough."""
    return str(os.getenv("AIPACS_SERIES_NUMBER_NORMALIZE", "1")).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def parse_series_number(value: Any) -> Optional[int]:
    """Return the series number as an int, or ``None`` when it is unusable.

    Tolerant of every spelling a PACS server may emit — int, float, ``"3"``,
    ``"03"``, ``"3.0"``, ``b"3"`` — and of every way it may say "absent"
    (``None``, ``""``, ``"None"``, ``"null"``, ``"N/A"``, ...).

    NEVER raises. This is the single predicate used to decide whether a series
    number is usable; do not re-implement ``int(...)`` on a server field
    anywhere else.
    """
    if value is None:
        return None
    # bool is an int subclass — a boolean is never a series number.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        try:
            if value != value:  # NaN
                return None
            return int(value)
        except (ValueError, OverflowError):
            return None
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("ascii", "ignore")
        except Exception:
            return None
    try:
        text = str(value).strip()
    except Exception:
        return None
    if text.lower() in _MISSING_TOKENS:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError, OverflowError):
        return None


def _series_lists(data: Any) -> Iterable[List[Dict[str, Any]]]:
    """Yield every series list found in a socket payload (dict or bare list)."""
    if isinstance(data, list):
        yield data
        return
    if not isinstance(data, dict):
        return
    for key in _SERIES_LIST_KEYS:
        candidate = data.get(key)
        if isinstance(candidate, list) and candidate:
            yield candidate


def normalize_series_entries(data: Any) -> int:
    """Give every series in ``data`` a usable numeric ``series_number``, in place.

    ``data`` is the payload returned by the socket endpoints
    (``GetStudyThumbnails`` / ``QuerySeriesThumbnails``) — a dict holding a
    ``series_thumbnails`` (or ``series``) list, or the bare list itself.

    Entries whose number already parses are **not touched at all**. Entries whose
    number is unusable get a deterministic, non-colliding synthetic number from
    the reserved band, plus two diagnostic keys:

        ``series_number_raw``        — whatever the server actually sent
        ``series_number_synthetic``  — ``True``

    Returns the number of entries that were given a synthetic number (0 in the
    overwhelmingly common healthy case, so callers can log only on anomaly).

    NEVER raises: normalization must not be able to break a fetch that would
    otherwise have succeeded.
    """
    if not is_normalize_enabled():
        return 0

    repaired = 0
    try:
        for series_list in _series_lists(data):
            repaired += _normalize_one_list(series_list)
    except Exception:  # pragma: no cover - belt & braces; never break the fetch
        return repaired
    return repaired


def _normalize_one_list(series_list: List[Dict[str, Any]]) -> int:
    taken: set[int] = set()
    missing: List[tuple] = []

    for index, series in enumerate(series_list):
        if not isinstance(series, dict):
            continue
        parsed = parse_series_number(series.get("series_number"))
        if parsed is None:
            # Deterministic ordering key: series_uid first (stable across fetches
            # and independent of the server's list order), list index as tiebreak
            # for the pathological "no uid either" case.
            missing.append((str(series.get("series_uid") or ""), index, series))
        else:
            taken.add(parsed)

    if not missing:
        # Healthy study: nothing rewritten, nothing allocated. Byte-identical.
        return 0

    missing.sort(key=lambda item: (item[0], item[1]))

    repaired = 0
    candidate = SYNTHETIC_SERIES_NUMBER_BASE + 1
    for _uid, _index, series in missing:
        while candidate in taken and candidate <= SYNTHETIC_SERIES_NUMBER_MAX:
            candidate += 1
        if candidate > SYNTHETIC_SERIES_NUMBER_MAX:
            # Unreachable in practice (would need >99_999 unnumbered series).
            # Leave the raw value alone rather than emit an offset-key-sized
            # number; the consumer-side tolerant parse still protects us.
            break
        series["series_number_raw"] = series.get("series_number")
        series["series_number"] = candidate
        series["series_number_synthetic"] = True
        taken.add(candidate)
        repaired += 1
        candidate += 1

    return repaired
