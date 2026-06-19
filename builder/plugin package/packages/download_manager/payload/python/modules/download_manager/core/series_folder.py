# -*- coding: utf-8 -*-
"""Series → on-disk folder-name resolution with collision disambiguation.

The download/viewer disk layout is ``{SOURCE_PATH}/{study_uid}/{series_number}/``.
A study is normally expected to have a unique ``series_number`` per series, but the
DICOM standard does not enforce it: a study can contain two genuinely different
SeriesInstanceUIDs that share one ``series_number`` (e.g. a secondary-capture /
derived series numbered the same as a primary acquisition). When that happens both
series resolve to the SAME folder and the second download silently OVERWRITES the
first — a real data-completeness loss (verified live 2026-06-19: patient study
…86503 had two series 203 — a 24-image and a 156-image series — and only one
survived on disk).

This helper makes the folder name collision-aware while keeping the common case
(no duplicate number) BYTE-IDENTICAL:

* No collision  -> ``str(series_number)`` (unchanged; the overwhelming common case).
* Collision     -> the series with the MOST images keeps the bare ``series_number``
  folder (so the primary/diagnostic series stays where the viewer already reads it,
  i.e. no display change), and every other series sharing that number gets a stable
  unique suffix ``"{series_number}__{sha1(series_uid)[:8]}"`` so its images are
  preserved in their own folder instead of being overwritten. Ties on image count
  break by the lowest ``series_uid`` so the result is deterministic and identical
  across the download subprocess and the viewer.

Pure (stdlib only) so it is unit-testable and importable from both the download
subprocess (``modules.download_manager``) and the PacsClient viewer.
"""
from __future__ import annotations

import hashlib
import os
from typing import Iterable, Tuple

# Master gate. Default ON. AIPACS_SERIES_NUMBER_DEDUP=0 restores the legacy
# behaviour (folder == bare series_number always; colliding series overwrite).
_DEDUP_ENABLED = (os.getenv("AIPACS_SERIES_NUMBER_DEDUP", "1") or "1").strip() != "0"


def series_number_collisions(study_series: Iterable[Tuple[object, object, object]]):
    """Return the set of ``str(series_number)`` values that are shared by >1
    distinct ``series_uid`` within the study.

    ``study_series`` is an iterable of ``(series_number, series_uid, image_count)``
    for ALL series in the study (image_count may be None for this call).
    """
    by_number = {}
    for series_number, series_uid, _ in study_series:
        num = str(series_number)
        uid = str(series_uid or "")
        if not uid:
            continue
        by_number.setdefault(num, set()).add(uid)
    return {num for num, uids in by_number.items() if len(uids) > 1}


def resolve_series_folder_name(series_number, series_uid, study_series) -> str:
    """On-disk folder NAME for one series within its study.

    Args:
        series_number: this series' number.
        series_uid:    this series' SeriesInstanceUID.
        study_series:  iterable of ``(series_number, series_uid, image_count)`` for
                       ALL series in the study (used only to detect/resolve a
                       collision; pass image_count as int or None).

    Returns ``str(series_number)`` in the common (no-collision) case — byte-identical
    to the legacy path — and a stable disambiguated name for the loser(s) of a
    same-number collision.
    """
    num = str(series_number)
    if not _DEDUP_ENABLED:
        return num

    uid = str(series_uid or "")
    # Gather siblings that share this exact series_number (distinct uids).
    siblings = []  # (image_count_int, uid)
    for s_num, s_uid, s_count in study_series:
        if str(s_num) != num:
            continue
        su = str(s_uid or "")
        if not su:
            continue
        try:
            cnt = int(s_count) if s_count is not None else 0
        except (TypeError, ValueError):
            cnt = 0
        siblings.append((cnt, su))

    # Unique uids only.
    uniq = {}
    for cnt, su in siblings:
        # keep the max image_count seen for a uid
        uniq[su] = max(cnt, uniq.get(su, 0))
    if len(uniq) <= 1 or not uid:
        return num  # no real collision → unchanged

    # Winner keeps the bare number: most images, tie → lowest uid (deterministic).
    winner = sorted(uniq.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    if uid == winner:
        return num
    suffix = hashlib.sha1(uid.encode("utf-8", "replace")).hexdigest()[:8]
    return f"{num}__{suffix}"
