"""Turn a study on disk into classifier candidates.

The classifier is deliberately pure - it scores plain objects. This module is
the adapter that produces them, and it is the only place that touches pydicom
or a live ``PatientWidget``.

Why headers straight off disk rather than the viewer's loaded metadata: at the
moment Eagle Eye opens, only the first series has actually been decoded into a
viewport. Waiting for every series to load just to decide which three to use
would cost seconds and defeat the point. One ``stop_before_pixels`` read per
series folder gives EchoTime, RepetitionTime, ImageOrientationPatient and the
descriptive tags for pennies, and the series that ARE loaded contribute their
richer instance lists on top.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .geometry import classify_plane, series_plane
from .series_classifier import SeriesCandidate

logger = logging.getLogger(__name__)

_DICOM_GLOBS = ("*.dcm", "*.DCM", "*.dicom", "*.DICOM")


def _dicom_files(folder: Path) -> List[Path]:
    """DICOM files directly inside ``folder``, each counted exactly once.

    The de-duplication is not defensive padding: on Windows ``Path.glob`` is
    case-insensitive, so globbing both ``*.dcm`` and ``*.DCM`` returned every
    file twice and doubled every slice count (an 11-slice sagittal reported 22).
    Slice count feeds the classifier's plausibility scoring, so a silent 2x is a
    real defect, not a cosmetic one.
    """
    seen = {}
    for pattern in _DICOM_GLOBS:
        try:
            for path in folder.glob(pattern):
                if path.is_file():
                    seen.setdefault(str(path).lower(), path)
        except OSError:
            continue
    if seen:
        return sorted(seen.values())
    # Some centres export without an extension; fall back to plain files.
    try:
        return sorted(p for p in folder.iterdir() if p.is_file())
    except OSError:
        return []


def _series_folders(study_path: Path) -> List[Path]:
    """Series folders of a study, supporting the flat single-series layout."""
    folders: List[Path] = []
    if _dicom_files(study_path):
        folders.append(study_path)
    try:
        for child in sorted(study_path.iterdir()):
            if child.is_dir() and _dicom_files(child):
                folders.append(child)
    except OSError:
        pass
    return folders


def _read_header(path: Path):
    try:
        import pydicom
        return pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    except Exception as exc:
        logger.debug("eagle_eye_lumbar: header read failed for %s: %s", path, exc)
        return None


def _tag(dataset, name, default=None):
    try:
        value = getattr(dataset, name, None)
        return default if value is None else value
    except Exception:
        return default


def candidate_from_header(
    dataset,
    index: int,
    slice_count: int,
    series_path: str = "",
    fallback_series_number: Any = "",
) -> SeriesCandidate:
    """Build one candidate from a single DICOM header dataset."""
    iop = _tag(dataset, "ImageOrientationPatient")
    return SeriesCandidate(
        index=index,
        series_uid=str(_tag(dataset, "SeriesInstanceUID", "") or ""),
        series_number=_tag(dataset, "SeriesNumber", fallback_series_number),
        series_description=str(_tag(dataset, "SeriesDescription", "") or ""),
        protocol_name=str(_tag(dataset, "ProtocolName", "") or ""),
        sequence_name=str(_tag(dataset, "SequenceName", "") or ""),
        image_type=_tag(dataset, "ImageType"),
        modality=str(_tag(dataset, "Modality", "") or ""),
        body_part=str(_tag(dataset, "BodyPartExamined", "") or ""),
        # Often the only place a region is named when BodyPartExamined is blank.
        study_description=str(_tag(dataset, "StudyDescription", "") or ""),
        plane=classify_plane(iop),
        slice_count=int(slice_count or 0),
        echo_time=_tag(dataset, "EchoTime"),
        repetition_time=_tag(dataset, "RepetitionTime"),
        inversion_time=_tag(dataset, "InversionTime"),
        scanning_sequence=_tag(dataset, "ScanningSequence"),
        sequence_variant=_tag(dataset, "SequenceVariant"),
        series_path=series_path,
    )


def probe_study_series(study_path: Any) -> List[SeriesCandidate]:
    """One candidate per series folder under ``study_path``.

    Reads exactly one header per series. Never raises: a folder whose header
    cannot be read is skipped and logged, because one unreadable series must
    not stop the other two slots from resolving.
    """
    root = Path(study_path) if study_path else None
    if root is None or not root.is_dir():
        return []

    candidates: List[SeriesCandidate] = []
    for folder in _series_folders(root):
        files = _dicom_files(folder)
        if not files:
            continue
        dataset = _read_header(files[0])
        if dataset is None:
            continue
        candidates.append(
            candidate_from_header(
                dataset,
                index=len(candidates),
                slice_count=len(files),
                series_path=str(folder),
                fallback_series_number=folder.name,
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Live-widget enrichment
# ---------------------------------------------------------------------------

def _thumbnail_series_number(entry: Dict[str, Any]) -> str:
    try:
        return str((entry.get("metadata") or {}).get("series", {}).get("series_number", "")).strip()
    except Exception:
        return ""


def _thumbnail_instances(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        return list((entry.get("metadata") or {}).get("instances", []) or [])
    except Exception:
        return []


def attach_thumbnail_indices(
    candidates: Sequence[SeriesCandidate],
    thumbnails_data: Sequence[Dict[str, Any]],
) -> None:
    """Point every candidate at its row in ``lst_thumbnails_data``.

    Matching is by series number, which is the key the thumbnail panel itself
    uses. A candidate with no matching thumbnail keeps ``thumbnail_index == -1``
    and can therefore never be loaded into a viewport - the caller treats that
    as an unresolved slot rather than loading the wrong series.
    """
    by_number: Dict[str, int] = {}
    for idx, entry in enumerate(thumbnails_data or ()):
        number = _thumbnail_series_number(entry)
        if number and number not in by_number:
            by_number[number] = idx

    for candidate in candidates:
        key = str(candidate.series_number or "").strip()
        if key in by_number:
            candidate.thumbnail_index = by_number[key]
            entry = thumbnails_data[candidate.thumbnail_index]
            instances = _thumbnail_instances(entry)
            # A fully loaded series carries the real instance list: prefer it,
            # it is what the viewer will actually be scrolling.
            if len(instances) > len(candidate.instances):
                candidate.instances = instances
                if len(instances) > 1:
                    candidate.slice_count = len(instances)
                plane = series_plane(instances)
                if plane and plane != "unknown":
                    candidate.plane = plane


def build_candidates_for_widget(patient_widget: Any) -> List[SeriesCandidate]:
    """Candidates for the study currently open in ``patient_widget``."""
    candidates = probe_study_series(resolve_study_path(patient_widget))
    try:
        attach_thumbnail_indices(candidates, list(getattr(patient_widget, "lst_thumbnails_data", []) or []))
    except Exception as exc:
        logger.warning("eagle_eye_lumbar: could not map candidates to thumbnails: %s", exc)
    return candidates


def resolve_study_path(patient_widget: Any) -> Any:
    """Folder holding the study currently open in ``patient_widget``.

    ``SOURCE_PATH / study_uid`` is preferred over ``import_folder_path``: in a
    multi-study tab the import path points at the tab's PRIMARY study, which is
    not necessarily the study the user is looking at.
    """
    study_uid = str(getattr(patient_widget, "study_uid", "") or "")
    if study_uid:
        try:
            from PacsClient.utils.config import SOURCE_PATH
            candidate = Path(SOURCE_PATH) / study_uid
            if candidate.is_dir():
                return candidate
        except Exception:
            pass
    return getattr(patient_widget, "import_folder_path", None)


# ---------------------------------------------------------------------------
# Study-level suitability
# ---------------------------------------------------------------------------

def study_lumbar_verdict(candidates: Sequence[SeriesCandidate]) -> tuple:
    """``(verdict, reason)`` for a probed study - lumbar / other / unknown.

    Reads the candidates' own headers rather than anything the GUI happens to
    hold in memory. That distinction is not academic: a real Siemens lumbar
    study (2026-08-26) reached the Eagle Eye button with an EMPTY
    StudyDescription in the local DB, NULL series body parts, and series named
    only 't2_tse_sag' / 't1_tse_sag' / 't2_tse_tra_msma'. Every one of its
    DICOM headers said ``BodyPartExamined = 'LSPINE'``.
    """
    from modules.ai_imaging.eagle_eye_modes import lumbar_verdict

    body_parts = [c.body_part for c in candidates if c.body_part]
    texts: List[str] = []
    for candidate in candidates:
        texts.extend([candidate.series_description, candidate.protocol_name,
                      candidate.study_description])
    return lumbar_verdict(body_parts, texts)


def study_lumbar_verdict_for_widget(patient_widget: Any, extra_texts: Sequence[Any] = ()) -> tuple:
    """``(verdict, reason, candidates)`` for the study open in ``patient_widget``."""
    candidates = build_candidates_for_widget(patient_widget)
    if not candidates:
        return "unknown", "no readable DICOM headers found for this study", candidates

    from modules.ai_imaging.eagle_eye_modes import lumbar_verdict

    body_parts = [c.body_part for c in candidates if c.body_part]
    texts: List[Any] = list(extra_texts or ())
    for candidate in candidates:
        texts.extend([candidate.series_description, candidate.protocol_name,
                      candidate.study_description])
    verdict, reason = lumbar_verdict(body_parts, texts)
    return verdict, reason, candidates
