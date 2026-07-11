"""Canonical viewport-overlay metadata provider (read-only TRUNK).

Single source of truth for the four-corner overlay TEXT so the FAST and Advanced
viewers render identical, deterministic metadata for the same series regardless
of which code path (DICOM header, local DB, or RIS/server payload) supplied the
raw values.

Design constraints (per the AI-PACS architecture hard rule):
- PURE stdlib. No Qt / VTK / pydicom / numpy / DB imports. This keeps the module
  unit-testable in isolation and — crucially — means it can NOT couple the three
  viewer execution domains. Each domain *calls* this provider; the provider never
  reaches back into a domain. Unification happens INSIDE the trunk, never across a
  domain boundary.
- Scope is DESCRIPTIVE OVERLAY TEXT only (patient name/id/sex/age, study
  date/time, institution, series description, modality, slice thickness). It does
  NOT decide series identity (series_number / offset keys), geometry, slice
  ordering or the slice counter — those are owned downstream and must not be
  touched here.

Policy (chosen with the user 2026-07-09):
- Patient Name/ID SOURCE precedence: DICOM (image) -> local DB copy -> server/RIS.
- PersonName COMPONENT: prefer the ALPHABETIC / Latin (English) group, falling
  back to the ideographic/phonetic (e.g. Persian) group.
- MISSING handling: "", "N/A", "NA", "none", "null", "-", "unknown" are ALL treated
  as missing so a better source can win; the rendered sentinel ``NA`` appears ONLY
  when a field is absent in every provided source.

``str(pydicom.PersonName)`` joins the component groups with ``=`` in the order
alphabetic=ideographic=phonetic, and within a group uses ``^`` to separate
family^given^middle^prefix^suffix. This module operates purely on that string
form, so callers can pass the already-stringified name (which every AI-PACS
metadata path already stores) without handing us a pydicom object.
"""
from __future__ import annotations

from typing import Optional

# Sentinel shown ONLY when a value is truly unavailable in every source.
MISSING = "NA"

# Values that must be treated as "no value" (case-insensitive, stripped) so a
# better source can win and the literal "N/A" never masks real data.
_MISSING_TOKENS = frozenset({"", "n/a", "na", "n\\a", "none", "null", "nan", "-", "--", "unknown"})

# Persian / Arabic script blocks — used to detect a non-Latin name component.
_PERSIAN_RANGES = (
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),  # Arabic Presentation Forms-B
)


def _clean(value) -> str:
    """Return a trimmed string, or "" if the value is missing/placeholder."""
    if value is None:
        return ""
    s = str(value).strip()
    if s.lower() in _MISSING_TOKENS:
        return ""
    return s


def first_present(*values) -> str:
    """First cleaned, non-missing value in precedence order (else "")."""
    for v in values:
        c = _clean(v)
        if c:
            return c
    return ""


def _has_latin(text: str) -> bool:
    return any(("a" <= ch.lower() <= "z") for ch in text)


def _has_persian(text: str) -> bool:
    for ch in text:
        o = ord(ch)
        if any(lo <= o <= hi for lo, hi in _PERSIAN_RANGES):
            return True
    return False


def _format_component(component: str) -> str:
    """DICOM PN display: '^' separates name parts -> render as spaces, collapsed."""
    return " ".join(p for p in component.replace("^", " ").split() if p)


def normalize_person_name(raw, prefer: str = "english") -> str:
    """Pick and format ONE display component from a DICOM PersonName string.

    ``prefer="english"`` -> the first component group that contains Latin letters
    (the DICOM *alphabetic* group by convention), else the first non-empty group.
    ``prefer="persian"`` -> the first group containing Persian/Arabic script, else
    the first non-empty group. Returns "" when there is no usable name.
    """
    s = _clean(raw)
    if not s:
        return ""
    groups = [g.strip() for g in s.split("=")]
    non_empty = [g for g in groups if g]
    if not non_empty:
        return ""

    if prefer == "persian":
        chosen = next((g for g in non_empty if _has_persian(g)), None)
        if chosen is None:
            chosen = non_empty[0]
    else:  # "english" (default)
        # Prefer a group with Latin letters (romanized/alphabetic component).
        chosen = next((g for g in non_empty if _has_latin(g)), None)
        if chosen is None:
            chosen = non_empty[0]  # no Latin anywhere -> first available (e.g. Persian)

    return _format_component(chosen) or _format_component(non_empty[0])


def _pick(dicom: dict, db: dict, server: dict, *keys) -> str:
    """First-present across (DICOM -> DB -> server) for any of the given keys."""
    vals = []
    for src in (dicom, db, server):
        for k in keys:
            vals.append(src.get(k))
    return first_present(*vals)


def build_overlay_metadata(
    *,
    dicom: Optional[dict] = None,
    db: Optional[dict] = None,
    server: Optional[dict] = None,
    series: Optional[dict] = None,
    name_pref: str = "english",
    missing: str = MISSING,
) -> dict:
    """Build the canonical overlay TEXT model from whatever sources are available.

    All four inputs are plain dicts (any may be None/empty). ``dicom`` is the
    image-derived metadata (highest precedence for identity per the chosen
    policy), ``db`` the local DB row, ``server`` the RIS/server payload, and
    ``series`` the per-series descriptive block (series_description, modality,
    slice thickness). Returns a dict whose every value is a display-ready string,
    equal to ``missing`` ("NA") only when the field is truly absent everywhere.
    """
    dicom = dicom or {}
    db = db or {}
    server = server or {}
    series = series or {}

    raw_name = _pick(dicom, db, server, "patient_name")
    name = normalize_person_name(raw_name, prefer=name_pref)

    def _or_missing(v: str) -> str:
        return v if v else missing

    return {
        "patient_name": _or_missing(name),
        "patient_id": _or_missing(_pick(dicom, db, server, "patient_id")),
        # DB may expose sex/age either as sex/age (schema columns) or the
        # patient_sex/patient_age aliases — accept both so neither path shows NA.
        "patient_sex": _or_missing(_pick(dicom, db, server, "patient_sex", "sex")),
        "patient_age": _or_missing(_pick(dicom, db, server, "patient_age", "age")),
        "study_date": _or_missing(_pick(dicom, db, server, "study_date")),
        "study_time": _or_missing(
            first_present(
                dicom.get("study_time"), db.get("study_time"),
                server.get("study_time"), series.get("series_time"),
            )
        ),
        "institution_name": _or_missing(
            _pick(dicom, db, server, "institution_name", "hospital_name")
        ),
        "series_description": _or_missing(
            first_present(
                series.get("series_description"), series.get("series_desc"),
                dicom.get("series_description"),
            )
        ),
        "modality": _or_missing(
            first_present(series.get("modality"), dicom.get("modality"))
        ),
        "slice_thickness": _or_missing(
            first_present(
                series.get("series_thk"), series.get("slice_thickness"),
                dicom.get("slice_thickness"),
            )
        ),
    }
