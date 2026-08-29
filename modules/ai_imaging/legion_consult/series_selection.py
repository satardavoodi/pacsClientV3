"""Pure selection policy for Legion Consult MRI series."""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from modules.ai_imaging.eagle_eye_lumbar.series_classifier import (
    SeriesCandidate,
    resolve_weighting,
)

from .models import SeriesSelectionPlan


class SelectionError(ValueError):
    """Raised when the mandatory Legion Consult selection is invalid."""


_NON_DIAGNOSTIC_PATTERN = re.compile(
    r"\b(locali[sz]er|scout|survey|three[ -]?plane|3[ -]?plane|"
    r"screen[ -]?save|dose|report|key[ -]?images?|calibration|shim|"
    r"field[ -]?map|phase|mip|projection)\b",
    re.IGNORECASE,
)


def series_key(candidate: SeriesCandidate) -> str:
    """Return a stable key without exposing a filesystem path."""
    if candidate.series_uid:
        return f"uid:{candidate.series_uid}"
    if str(candidate.series_number).strip():
        return f"number:{candidate.series_number}"
    return f"index:{candidate.index}"


def is_eligible_diagnostic_mr(candidate: SeriesCandidate) -> bool:
    """Exclude non-MR and clearly non-diagnostic utility series."""
    if str(candidate.modality or "").upper() != "MR":
        return False
    if _NON_DIAGNOSTIC_PATTERN.search(candidate.text):
        return False
    image_type = " ".join(candidate.image_type) if isinstance(candidate.image_type, (list, tuple)) else str(candidate.image_type or "")
    upper_image_type = image_type.upper()
    if "LOCALIZER" in upper_image_type or "PROJECTION IMAGE" in upper_image_type:
        return False
    return True


def _role(candidate: SeriesCandidate) -> str:
    return str(resolve_weighting(candidate).get("weighting") or "unknown")


def default_candidate_for_role(
    candidates: Sequence[SeriesCandidate],
    role: str,
    source: SeriesCandidate,
) -> SeriesCandidate | None:
    """Suggest a T1/T2, preferring source reuse and the source plane."""
    normalized_role = str(role or "").lower()
    if normalized_role not in {"t1", "t2"}:
        raise ValueError("Role must be either 't1' or 't2'.")
    if is_eligible_diagnostic_mr(source) and _role(source) == normalized_role:
        return source

    matches = [
        candidate
        for candidate in candidates
        if is_eligible_diagnostic_mr(candidate) and _role(candidate) == normalized_role
    ]
    if not matches:
        return None
    source_plane = str(source.plane or "").lower()
    matches.sort(
        key=lambda candidate: (
            str(candidate.plane or "").lower() != source_plane,
            -int(candidate.slice_count or 0),
            int(candidate.index),
        )
    )
    return matches[0]


def _require_candidate(
    name: str,
    candidate: SeriesCandidate | None,
    eligible_by_key: dict[str, SeriesCandidate],
) -> SeriesCandidate:
    if candidate is None:
        raise SelectionError(f"A {name} series assignment is required.")
    key = series_key(candidate)
    if key not in eligible_by_key:
        raise SelectionError(f"The assigned {name} series is not an eligible MRI series.")
    return eligible_by_key[key]


def _manifest(candidate: SeriesCandidate, *, roles: Iterable[str]) -> dict:
    return {
        "series_key": series_key(candidate),
        "series_number": candidate.series_number,
        "series_description": candidate.series_description,
        "plane": candidate.plane,
        "slice_count": int(candidate.slice_count or 0),
        "weighting": _role(candidate),
        "roles": tuple(roles),
    }


def build_selection_plan(
    *,
    study_uid: str,
    candidates: Sequence[SeriesCandidate],
    source: SeriesCandidate | None,
    t1: SeriesCandidate | None,
    t2: SeriesCandidate | None,
    optional_keys: Sequence[str] = (),
    select_all: bool = False,
) -> SeriesSelectionPlan:
    """Validate mandatory assignments and produce a de-duplicated series plan."""
    if not str(study_uid or "").strip():
        raise SelectionError("A Study Instance UID is required.")
    eligible = [candidate for candidate in candidates if is_eligible_diagnostic_mr(candidate)]
    eligible_by_key = {series_key(candidate): candidate for candidate in eligible}
    source = _require_candidate("source", source, eligible_by_key)
    t1 = _require_candidate("T1", t1, eligible_by_key)
    t2 = _require_candidate("T2", t2, eligible_by_key)

    requested_keys = [series_key(source), series_key(t1), series_key(t2)]
    if select_all:
        requested_keys.extend(series_key(candidate) for candidate in eligible)
    else:
        unknown_keys = [key for key in optional_keys if key not in eligible_by_key]
        if unknown_keys:
            raise SelectionError("An optional series is not an eligible MRI series.")
        requested_keys.extend(optional_keys)

    selected_keys = tuple(dict.fromkeys(requested_keys))
    roles_by_key: dict[str, list[str]] = {key: [] for key in selected_keys}
    roles_by_key[series_key(source)].append("source")
    roles_by_key[series_key(t1)].append("t1")
    roles_by_key[series_key(t2)].append("t2")
    for key in selected_keys:
        if not roles_by_key[key]:
            roles_by_key[key].append("optional")

    manifest = tuple(
        _manifest(eligible_by_key[key], roles=roles_by_key[key]) for key in selected_keys
    )
    estimated_images = sum(int(eligible_by_key[key].slice_count or 0) for key in selected_keys)
    return SeriesSelectionPlan(
        study_uid=str(study_uid),
        source_series_key=series_key(source),
        t1_series_key=series_key(t1),
        t2_series_key=series_key(t2),
        selected_series_keys=selected_keys,
        select_all=bool(select_all),
        estimated_image_count=estimated_images,
        series_manifest=manifest,
    )
