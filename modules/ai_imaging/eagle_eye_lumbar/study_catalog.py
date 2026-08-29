"""Which studies is this patient tab actually holding?

Eagle Eye must not pick arbitrarily when a patient carries more than one exam,
so it first needs an honest list of what is loaded. A patient tab can hold
several studies at once (multi-study grouping, merged previous exams), and the
study the reader is looking at is not always the tab's primary one.

The UIDs are collected from every place the tab records them, then enriched from
the local database, then - only for what the database cannot answer - from the
DICOM headers on disk.

No Qt. The database and header reads are both wrapped, so a catalogue can always
be produced even when one source is unavailable.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Studies that are not imaging: the Documents pseudo-study every patient carries
# (scanned request forms, reports) must never appear in a study picker.
_NON_IMAGING_MODALITIES = {"DOC", "SR", "PR", "KO"}


class StudyCandidate:
    """One study the user could plausibly mean."""

    __slots__ = ("study_uid", "description", "study_date", "modality",
                 "body_part", "series_count", "path", "is_current")

    def __init__(self, study_uid: str, description: str = "", study_date: str = "",
                 modality: str = "", body_part: str = "", series_count: int = 0,
                 path: Optional[Any] = None, is_current: bool = False):
        self.study_uid = str(study_uid or "")
        self.description = str(description or "")
        self.study_date = str(study_date or "")
        self.modality = str(modality or "").upper()
        self.body_part = str(body_part or "")
        self.series_count = int(series_count or 0)
        self.path = path
        self.is_current = bool(is_current)

    @property
    def formatted_date(self) -> str:
        """``20260820`` -> ``2026-08-20``; anything else is passed through."""
        raw = self.study_date.strip()
        if len(raw) == 8 and raw.isdigit():
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
        return raw

    @property
    def label(self) -> str:
        """One line a reader can identify the exam by."""
        name = self.description.strip() or self.body_part.strip() or "Study"
        if self.modality and not name.upper().startswith(self.modality):
            name = f"{self.modality} {name}"
        date = self.formatted_date
        return f"{name} — {date}" if date else name

    @property
    def detail(self) -> str:
        bits = []
        if self.series_count:
            bits.append(f"{self.series_count} series")
        if self.body_part:
            bits.append(self.body_part)
        if self.is_current:
            bits.append("currently open")
        return " · ".join(bits)

    @property
    def is_imaging(self) -> bool:
        parts = {p.strip().upper() for p in self.modality.replace(",", " ").split()}
        return bool(parts - _NON_IMAGING_MODALITIES) if parts else True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "study_instance_uid": self.study_uid,
            "study_description": self.description,
            "study_date": self.study_date,
            "modality": self.modality,
            "body_part": self.body_part,
            "series_count": self.series_count,
            "was_current_tab_study": self.is_current,
        }


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def _study_uids_in_tab(patient_widget: Any) -> List[str]:
    """Every study UID this tab records, current one first, in order, no repeats."""
    ordered: List[str] = []

    def add(value: Any) -> None:
        uid = str(value or "").strip()
        if uid and uid not in ordered:
            ordered.append(uid)

    add(getattr(patient_widget, "study_uid", ""))

    # Multi-study thumbnail grouping: [(study_uid, slot, [(key, entry), ...])]
    try:
        for group in list(getattr(patient_widget, "_multistudy_viewer_groups", []) or []):
            if isinstance(group, (list, tuple)) and group:
                add(group[0])
    except Exception:
        pass

    try:
        for thumb in list(getattr(patient_widget, "lst_thumbnails_data", []) or []):
            series = ((thumb or {}).get("metadata", {}) or {}).get("series", {}) or {}
            add(series.get("study_uid"))
    except Exception:
        pass

    try:
        for entry in (getattr(patient_widget, "_server_series_info", {}) or {}).values():
            if isinstance(entry, dict):
                add(entry.get("study_uid"))
    except Exception:
        pass

    return ordered


def _from_database(study_uid: str) -> Optional[Dict[str, Any]]:
    try:
        from database.manager import get_study_info_with_series
        return get_study_info_with_series(study_uid)
    except Exception as exc:
        logger.debug("eagle_eye: study lookup failed for %s: %s", study_uid, exc)
        return None


def _study_path(study_uid: str) -> Optional[Path]:
    try:
        from PacsClient.utils.config import SOURCE_PATH
        path = Path(SOURCE_PATH) / study_uid
        return path if path.is_dir() else None
    except Exception:
        return None


def _from_headers(study_uid: str, path: Path) -> Dict[str, Any]:
    """Fill in what the database could not, straight from the DICOM headers.

    The local database is not always complete - the study that exposed this
    whole area had an empty study_description and NULL series body parts - so a
    study picker built only from database rows can show unidentifiable rows.
    """
    from .series_probe import probe_study_series

    candidates = probe_study_series(path)
    if not candidates:
        return {}
    first = candidates[0]
    body_parts = [c.body_part for c in candidates if c.body_part]
    modalities = sorted({c.modality for c in candidates if c.modality})
    return {
        "study_description": first.study_description,
        "modality": ", ".join(modalities),
        "body_part": body_parts[0] if body_parts else "",
        "series_count": len(candidates),
    }


def collect_studies(patient_widget: Any, imaging_only: bool = True) -> List[StudyCandidate]:
    """Studies loaded in ``patient_widget``, best-identified first."""
    current = str(getattr(patient_widget, "study_uid", "") or "").strip()
    out: List[StudyCandidate] = []

    for uid in _study_uids_in_tab(patient_widget):
        info = _from_database(uid) or {}
        path = _study_path(uid)

        needs_headers = path is not None and (
            not info
            or not str(info.get("study_description") or "").strip()
            or not str(info.get("body_part") or "").strip()
        )
        if needs_headers:
            try:
                for key, value in _from_headers(uid, path).items():
                    if value and not str(info.get(key) or "").strip():
                        info[key] = value
            except Exception as exc:
                logger.debug("eagle_eye: header enrichment failed for %s: %s", uid, exc)

        out.append(StudyCandidate(
            study_uid=uid,
            description=info.get("study_description", ""),
            study_date=info.get("study_date", ""),
            modality=info.get("modality", ""),
            body_part=info.get("body_part", ""),
            series_count=info.get("series_count", 0) or len(info.get("series", []) or []),
            path=path,
            is_current=(uid == current),
        ))

    if imaging_only:
        imaging = [s for s in out if s.is_imaging]
        # Never strand the user: if the filter removed everything, show the lot.
        out = imaging or out

    out.sort(key=lambda s: (not s.is_current, s.study_date), reverse=False)
    return out


def needs_study_prompt(studies: Sequence[StudyCandidate]) -> bool:
    """True when Eagle Eye must ask which study to use.

    One study is not a choice. More than one always is: two exams from the same
    day are exactly the case where guessing "the current tab study" quietly does
    the wrong thing.
    """
    return len(studies) > 1
