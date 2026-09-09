"""Bounded MR-myelography context for the lumbar central-canal screen.

MR myelography is an overview cue only. It never assigns a lumbar level, changes
an immutable axial group, or substitutes for level-bound axial T2 assessment.
"""

from __future__ import annotations

import re
from itertools import islice
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

import numpy as np
from PIL import Image


MAX_CONTEXT_SERIES = 2
MAX_DISCOVERY_FILES = 192
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_DECODE_PIXELS = 16_000_000
_EXPLICIT_MYELO = re.compile(r"(?:^|[^a-z0-9])(myelo(?:graphy)?|mrm)(?:[^a-z0-9]|$)", re.I)


def _text(candidate: Any) -> str:
    return " ".join(str(getattr(candidate, field, "") or "") for field in (
        "series_description", "protocol_name", "sequence_name",
    ))


def select_context_sources(candidates: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """Select only explicitly identified MR-myelography series, with a hard cap."""
    ranked = []
    for position, candidate in enumerate(candidates):
        if str(getattr(candidate, "modality", "") or "").upper() != "MR":
            continue
        path = str(getattr(candidate, "series_path", "") or "")
        uid = str(getattr(candidate, "series_uid", "") or "")
        if not path or not uid or not _EXPLICIT_MYELO.search(_text(candidate)):
            continue
        plane = str(getattr(candidate, "plane", "") or "unknown").lower()
        plane_rank = {"coronal": 0, "sagittal": 1}.get(plane, 2)
        ranked.append((plane_rank, position, candidate))
    sources = {}
    for number, (_rank, _position, candidate) in enumerate(
        sorted(ranked, key=lambda item: item[:2])[:MAX_CONTEXT_SERIES], start=1
    ):
        sources[f"canal_myelographic_{number:02d}"] = {
            "series_path": str(candidate.series_path),
            "series_uid": str(candidate.series_uid),
            "plane": str(getattr(candidate, "plane", "") or "unknown"),
            "selection_basis": "explicit_mr_myelography_metadata",
        }
    return sources


def discover_context_sources(
    source_series: dict[str, dict[str, Any]], study_uid: str,
) -> dict[str, dict[str, Any]]:
    """Discover explicit myelography siblings without exporting their identity."""
    if not str(study_uid or "").strip():
        return {}
    if any(str(key).startswith("canal_myelographic_") for key in source_series):
        return {
            key: dict(value) for key, value in source_series.items()
            if str(key).startswith("canal_myelographic_")
        }
    roots = []
    for source in source_series.values():
        raw_path = str(source.get("series_path") or "")
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            continue
        root = path.parent
        if root != Path(root.anchor) and root.is_dir() and root not in roots:
            roots.append(root)
    candidates = []
    try:
        import pydicom
    except Exception:
        return {}
    for root in roots[:1]:
        root_entries = list(islice(root.iterdir(), 65))
        if len(root_entries) > 64:
            continue
        directories = sorted(
            (item for item in root_entries if item.is_dir()),
            key=lambda item: item.name.lower(),
        )
        for directory in islice(directories, 64):
            directory_entries = list(islice(directory.iterdir(), MAX_DISCOVERY_FILES + 1))
            if len(directory_entries) > MAX_DISCOVERY_FILES:
                continue
            paths = sorted(
                (item for item in directory_entries if item.is_file()),
                key=lambda item: item.name.lower(),
            )
            for path in islice(paths, 8):
                try:
                    ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
                    if (
                        str(getattr(ds, "StudyInstanceUID", "") or "") != str(study_uid or "")
                        or str(getattr(ds, "Modality", "") or "").upper() != "MR"
                    ):
                        continue
                    candidates.append(SimpleNamespace(
                        series_description=str(getattr(ds, "SeriesDescription", "") or ""),
                        protocol_name=str(getattr(ds, "ProtocolName", "") or ""),
                        sequence_name=str(getattr(ds, "SequenceName", "") or ""),
                        modality="MR", plane="unknown", series_path=str(directory),
                        series_uid=str(getattr(ds, "SeriesInstanceUID", "") or ""),
                    ))
                    break
                except Exception:
                    continue
    return select_context_sources(candidates)


def _source_files(source: dict[str, Any]) -> list[Path]:
    raw_path = str(source.get("series_path") or "")
    if not raw_path:
        return []
    path = Path(raw_path)
    if not path.is_absolute():
        return []
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    entries = list(islice(path.iterdir(), MAX_DISCOVERY_FILES + 1))
    if len(entries) > MAX_DISCOVERY_FILES:
        return []
    files = [item for item in entries if item.is_file()]
    return sorted(files, key=lambda item: item.name.lower())


def render_context(
    source_series: dict[str, dict[str, Any]], study_uid: str,
    *, local_provenance: list[dict[str, Any]] | None = None,
) -> tuple[list[tuple[Image.Image, dict[str, Any]]], list[str]]:
    """Decode at most one bounded overview image per selected context series."""
    try:
        import pydicom
        from pydicom.pixel_data_handlers.util import apply_modality_lut, apply_voi_lut
    except Exception:
        return [], ["decoder_unavailable"]
    rendered = []
    warnings = []
    for key, source in source_series.items():
        if not str(key).startswith("canal_myelographic_"):
            continue
        if not str(study_uid or "").strip() or not str(source.get("series_uid") or "").strip():
            warnings.append("identity_missing")
            continue
        accepted = False
        files = _source_files(source)
        for path in files:
            try:
                if path.stat().st_size > MAX_SOURCE_BYTES:
                    warnings.append("source_too_large")
                    continue
                ds = pydicom.dcmread(str(path), force=True)
                if (
                    str(getattr(ds, "StudyInstanceUID", "") or "") != str(study_uid or "")
                    or str(getattr(ds, "SeriesInstanceUID", "") or "")
                    != str(source.get("series_uid") or "")
                ):
                    warnings.append("identity_mismatch")
                    continue
                if str(getattr(ds, "Modality", "") or "").upper() != "MR":
                    warnings.append("wrong_modality")
                    continue
                if str(getattr(ds, "BurnedInAnnotation", "") or "").upper() == "YES":
                    warnings.append("burned_in_annotation")
                    continue
                rows, columns = int(ds.Rows), int(ds.Columns)
                frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
                if rows * columns * frames > MAX_DECODE_PIXELS:
                    warnings.append("pixel_limit")
                    continue
                array = np.asarray(ds.pixel_array)
                frame_index = 0
                if array.ndim == 3 and array.shape[-1] not in (3, 4):
                    frame_index = array.shape[0] // 2
                    array = array[frame_index]
                if array.ndim != 2:
                    warnings.append("unsupported_pixel_shape")
                    continue
                array = np.asarray(apply_modality_lut(array, ds), dtype=np.float32)
                try:
                    array = np.asarray(apply_voi_lut(array, ds), dtype=np.float32)
                except Exception:
                    pass
                finite = array[np.isfinite(array)]
                if not finite.size:
                    warnings.append("nonfinite_pixels")
                    continue
                low, high = np.percentile(finite, (1.0, 99.0))
                if high <= low:
                    warnings.append("constant_pixels")
                    continue
                pixels = np.clip((array - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)
                if str(getattr(ds, "PhotometricInterpretation", "")).upper() == "MONOCHROME1":
                    pixels = 255 - pixels
                rendered.append((Image.fromarray(pixels, mode="L").convert("RGB"), {
                    "tile_id": f"canal-myelo-{len(rendered) + 1:02d}",
                    "source_key": str(key),
                    "source_frame_index": frame_index,
                    "role": "myelographic_context",
                    "plane": str(source.get("plane") or "unknown"),
                    "selection_basis": str(source.get("selection_basis") or ""),
                    "localization_allowed": False,
                    "level_assignment_allowed": False,
                    "interpretation": "canal_caliber_overview_only",
                }))
                if local_provenance is not None:
                    local_provenance.append({
                        "source_key": str(key), "source_file": str(path),
                        "source_frame_index": frame_index,
                        "series_uid": str(ds.SeriesInstanceUID),
                        "sop_instance_uid": str(getattr(ds, "SOPInstanceUID", "") or ""),
                    })
                accepted = True
                break
            except Exception:
                warnings.append("decode_failed")
        if not accepted and not files:
            warnings.append("source_unavailable")
        if len(rendered) >= MAX_CONTEXT_SERIES:
            break
    return rendered, list(dict.fromkeys(warnings))
