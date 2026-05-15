from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import logging
import math
from pathlib import Path
from typing import Any

import re

import numpy as np

from . import utils


logger = logging.getLogger(__name__)


def _norm_path(path: str) -> str:
    return str(path or "").replace("\\", "/").lower()


def _hash_paths(paths: list[str] | tuple[str, ...]) -> str:
    text = "\n".join(_norm_path(path) for path in (paths or []))
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _axis_labels(axis: int) -> tuple[str, str]:
    if axis == 0:
        return "Right", "Left"
    if axis == 1:
        return "Anterior", "Posterior"
    return "Inferior", "Superior"


def _slice_normal_from_iop(iop: list[float] | tuple[float, ...] | None) -> np.ndarray | None:
    if not iop or len(iop) < 6:
        return None
    try:
        row = np.asarray(iop[0:3], dtype=float)
        col = np.asarray(iop[3:6], dtype=float)
        normal = np.cross(row, col)
        length = float(np.linalg.norm(normal))
        if length <= 1e-9:
            return None
        return normal / length
    except Exception:
        return None


def _plane_from_normal(normal: np.ndarray | list[float] | tuple[float, ...] | None) -> tuple[str, int | None, float]:
    if normal is None:
        return "OBLIQUE", None, 0.0
    vec = np.asarray(normal, dtype=float)
    length = float(np.linalg.norm(vec))
    if length <= 1e-9:
        return "OBLIQUE", None, 0.0
    vec = vec / length
    abs_vec = np.abs(vec)
    axis = int(np.argmax(abs_vec))
    dominance = float(abs_vec[axis])
    if dominance < 0.9:
        return "OBLIQUE", axis, dominance
    if axis == 0:
        return "SAGITTAL", axis, dominance
    if axis == 1:
        return "CORONAL", axis, dominance
    return "AXIAL", axis, dominance


def _label_pair_from_ipps(
    first_ipp: tuple[float, float, float] | None,
    last_ipp: tuple[float, float, float] | None,
    axis: int | None,
) -> tuple[str, str]:
    if first_ipp is None or last_ipp is None or axis is None:
        return "?", "?"
    neg_label, pos_label = _axis_labels(axis)
    first_val = float(first_ipp[axis])
    last_val = float(last_ipp[axis])
    if math.isclose(first_val, last_val, abs_tol=1e-6):
        return neg_label, pos_label
    if first_val < last_val:
        return neg_label, pos_label
    return pos_label, neg_label


def _is_extremity_or_joint(body_part: str) -> bool:
    body_upper = str(body_part or "").upper()
    return any(
        token in body_upper
        for token in (
            "KNEE", "ANKLE", "FOOT", "HIP", "LEG", "FEMUR", "TIBIA",
            "SHOULDER", "ELBOW", "WRIST", "HAND", "HUMERUS", "FOREARM",
            "JOINT", "EXTREM",
        )
    )


# ---------------------------------------------------------------------------
# AXIAL-LIKE extremity helpers
# ---------------------------------------------------------------------------

_AXIAL_LIKE_KEYWORD_TOKENS: frozenset[str] = frozenset({
    "AX", "AXIAL", "TRA", "TRANSVERSE", "TRANS",
})

# Body parts known to commonly have oblique axial acquisitions in clinical MRI.
_OBLIQUE_AXIAL_EXTREMITY_BODY_PARTS: frozenset[str] = frozenset({
    "SHOULDER", "WRIST", "HAND", "KNEE", "ANKLE", "FOOT", "ELBOW",
})

# Canonical extremity tokens ordered longest-first to avoid partial shadowing.
_EXTREMITY_CANONICAL_TOKENS: tuple[str, ...] = (
    "SHOULDER", "FOREARM", "HUMERUS",
    "ELBOW", "ANKLE",
    "WRIST", "EXTREM", "JOINT",
    "FEMUR", "TIBIA",
    "KNEE", "FOOT", "HAND", "HIP", "LEG",
)


def _normalize_body_part_canonical(body_part: str) -> str:
    """Extract canonical extremity token from a raw DICOM BodyPartExamined string."""
    upper = re.sub(r'[\s_\-,./\\]+', '', (body_part or "").upper())
    for lat in ("BILATERAL", "LEFT", "RIGHT", "LT", "RT", "BL", "BI"):
        upper = upper.replace(lat, "")
    for token in _EXTREMITY_CANONICAL_TOKENS:
        if token in upper:
            return token
    return (body_part or "").upper().strip() or "UNKNOWN"


def _normalize_laterality(laterality: str) -> str:
    """Normalize laterality to canonical form: R, L, B, or ''."""
    lat = (laterality or "").upper().strip()
    if lat in ("R", "RIGHT", "RT"):
        return "R"
    if lat in ("L", "LEFT", "LT"):
        return "L"
    if lat in ("B", "BI", "BILATERAL", "BL"):
        return "B"
    return lat


def _matches_axial_keywords(text: str) -> bool:
    """Return True if text contains an axial-indicating keyword token.

    Splits on non-alphanumeric separators so compound names like
    ``TSE_AX``, ``PD_AX``, ``T2_AX`` all match via the ``AX`` segment.
    """
    if not text:
        return False
    tokens = re.split(r'[_\-\s/\\,.:;]+', text.upper())
    return any(tok in _AXIAL_LIKE_KEYWORD_TOKENS for tok in tokens if tok)


def _check_axial_like_extremity(
    *,
    plane: str,
    body_part: str,
    normalized_body_part: str,
    dominant_axis: int | None,
    dominance_value: float,
    series_description: str,
    protocol_name: str,
) -> tuple[bool, str, str]:
    """Determine if an extremity/joint series is clinically AXIAL_LIKE.

    Priority order:
      A. SeriesDescription / ProtocolName keyword match  -> HIGH confidence
      B. Geometric plane is already AXIAL                -> HIGH confidence
      C. OBLIQUE + known oblique-axial extremity body part with dominance < 0.9
                                                        -> MEDIUM confidence

    Returns:
        (is_axial_like: bool, reason: str, confidence: str)
    """
    if not _is_extremity_or_joint(body_part):
        return False, "not_extremity", "N/A"

    # Criterion A: DICOM keyword match in SeriesDescription or ProtocolName.
    desc_match = _matches_axial_keywords(series_description)
    proto_match = _matches_axial_keywords(protocol_name)
    if desc_match or proto_match:
        source = "series_description" if desc_match else "protocol_name"
        return True, f"keyword_match:{source}", "HIGH"

    # Criterion B: True geometric AXIAL plane.
    if plane.upper() == "AXIAL":
        return True, "true_axial_plane", "HIGH"

    # Criterion C: OBLIQUE + known oblique-axial extremity + weak dominance.
    if plane.upper() == "OBLIQUE" and normalized_body_part in _OBLIQUE_AXIAL_EXTREMITY_BODY_PARTS:
        return True, "oblique_extremity_heuristic", "MEDIUM"

    return False, "not_axial_like", "N/A"


def _resolve_display_labels(
    *,
    plane: str,
    body_part: str,
    patient_position: str,
    geometry_first_label: str,
    geometry_last_label: str,
    dominant_axis: int | None,
    dominance_value: float = 0.0,
    series_description: str = "",
    protocol_name: str = "",
) -> tuple[str, str, str, str, bool, tuple[bool, str, str]]:
    """Resolve display labels and convention for a series.

    Returns a 6-tuple:
        (desired_first_label, desired_last_label, sort_target_first_label,
         display_convention, unresolved_flag, axial_like_info)
    where axial_like_info = (is_axial_like, reason, confidence).
    """
    plane_upper = str(plane or "OBLIQUE").upper()
    body_upper = str(body_part or "")
    unresolved = False
    _no_axial_like: tuple[bool, str, str] = (False, "not_axial_like", "N/A")

    # Check AXIAL_LIKE_EXTREMITY first — covers keyword match, true AXIAL, and oblique heuristic.
    # This heuristic is intentionally limited to recognized extremity/joint body parts;
    # do not generalize it to non-extremity oblique series without new validation data.
    normalized_bp = _normalize_body_part_canonical(body_upper)
    axial_like_info = _check_axial_like_extremity(
        plane=plane_upper,
        body_part=body_upper,
        normalized_body_part=normalized_bp,
        dominant_axis=dominant_axis,
        dominance_value=dominance_value,
        series_description=series_description,
        protocol_name=protocol_name,
    )
    if axial_like_info[0]:
        # Z-dominant (or true AXIAL): standard Superior-based reversal.
        # Non-Z-dominant: sentinel "Z_SUPERIOR" triggers Z-component reversal in caller.
        sort_target = "Superior" if dominant_axis == 2 else "Z_SUPERIOR"
        return "Proximal", "Distal", sort_target, "AXIAL_LIKE_EXTREMITY", False, axial_like_info

    if plane_upper == "AXIAL":
        return "Superior", "Inferior", "Superior", "AXIAL_SUPERIOR_TO_INFERIOR", unresolved, _no_axial_like
    if plane_upper == "SAGITTAL":
        return "Right", "Left", "Right", "SAGITTAL_RIGHT_TO_LEFT", False, _no_axial_like
    if plane_upper == "CORONAL":
        return "Anterior", "Posterior", "Anterior", "CORONAL_ANTERIOR_TO_POSTERIOR", False, _no_axial_like
    return geometry_first_label, geometry_last_label, geometry_first_label, f"{plane_upper}_GEOMETRY_ORDER", False, _no_axial_like


def _metadata_path_hash(instances: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> str:
    return _hash_paths([str(inst.get("instance_path") or "") for inst in (instances or [])])


@dataclass(frozen=True)
class GeometryIndexedInstance:
    instance_number: int
    instance_path: str
    rows: int
    columns: int
    window_width: float | None
    window_center: float | None
    is_rgb: bool
    sop_uid: str
    image_orientation_patient: tuple[float, float, float, float, float, float] | None
    image_position_patient: tuple[float, float, float] | None
    pixel_spacing: tuple[float, float] | None
    slice_thickness: float | None
    spacing_between_slices: float | None
    rescale_slope: float
    rescale_intercept: float
    bits_allocated: int
    pixel_representation: int
    study_uid: str = ""
    series_uid: str = ""
    series_number: str = ""
    slice_pos: float = 0.0

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "instance_number": self.instance_number,
            "instance_path": self.instance_path,
            "rows": self.rows,
            "columns": self.columns,
            "window_width": self.window_width,
            "window_center": self.window_center,
            "is_rgb": self.is_rgb,
            "sop_uid": self.sop_uid,
            "image_orientation_patient": list(self.image_orientation_patient) if self.image_orientation_patient is not None else None,
            "image_position_patient": list(self.image_position_patient) if self.image_position_patient is not None else None,
            "pixel_spacing": list(self.pixel_spacing) if self.pixel_spacing is not None else None,
            "slice_thickness": self.slice_thickness,
            "spacing_between_slices": self.spacing_between_slices,
            "rescale_slope": self.rescale_slope,
            "rescale_intercept": self.rescale_intercept,
            "bits_allocated": self.bits_allocated,
            "pixel_representation": self.pixel_representation,
            "study_uid": self.study_uid,
            "series_uid": self.series_uid,
            "series_number": self.series_number,
            "slice_pos": self.slice_pos,
        }

    def to_dict(self) -> dict[str, Any]:
        data = self.to_metadata_dict()
        data["image_orientation_patient"] = tuple(data["image_orientation_patient"]) if data["image_orientation_patient"] is not None else None
        data["image_position_patient"] = tuple(data["image_position_patient"]) if data["image_position_patient"] is not None else None
        data["pixel_spacing"] = tuple(data["pixel_spacing"]) if data["pixel_spacing"] is not None else None
        return data

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GeometryIndexedInstance":
        return cls(
            instance_number=int(payload.get("instance_number") or 0),
            instance_path=str(payload.get("instance_path") or ""),
            rows=int(payload.get("rows") or 0),
            columns=int(payload.get("columns") or 0),
            window_width=payload.get("window_width"),
            window_center=payload.get("window_center"),
            is_rgb=bool(payload.get("is_rgb")),
            sop_uid=str(payload.get("sop_uid") or ""),
            image_orientation_patient=tuple(payload.get("image_orientation_patient")) if payload.get("image_orientation_patient") is not None else None,
            image_position_patient=tuple(payload.get("image_position_patient")) if payload.get("image_position_patient") is not None else None,
            pixel_spacing=tuple(payload.get("pixel_spacing")) if payload.get("pixel_spacing") is not None else None,
            slice_thickness=payload.get("slice_thickness"),
            spacing_between_slices=payload.get("spacing_between_slices"),
            rescale_slope=float(payload.get("rescale_slope") or 1.0),
            rescale_intercept=float(payload.get("rescale_intercept") or 0.0),
            bits_allocated=int(payload.get("bits_allocated") or 16),
            pixel_representation=int(payload.get("pixel_representation") or 1),
            study_uid=str(payload.get("study_uid") or ""),
            series_uid=str(payload.get("series_uid") or ""),
            series_number=str(payload.get("series_number") or ""),
            slice_pos=float(payload.get("slice_pos") or 0.0),
        )


@dataclass(frozen=True)
class SeriesGeometryIndex:
    series_uid: str
    study_uid: str
    modality: str
    body_part: str
    laterality: str
    patient_position: str
    plane: str
    row_cosines: tuple[float, float, float]
    col_cosines: tuple[float, float, float]
    slice_normal: tuple[float, float, float]
    sorted_instances_geometry_order: tuple[GeometryIndexedInstance, ...]
    display_instances_order: tuple[GeometryIndexedInstance, ...]
    dicom_files_for_itk: tuple[str, ...]
    sop_uid_by_display_index: tuple[str, ...]
    ipp_by_display_index: tuple[tuple[float, float, float] | None, ...]
    iop_by_display_index: tuple[tuple[float, float, float, float, float, float] | None, ...]
    display_order_hash: str
    geometry_order_hash: str
    first_display_label: str
    last_display_label: str
    display_convention: str
    display_to_geometry_index: tuple[int, ...] = field(default_factory=tuple)
    geometry_to_display_index: tuple[int, ...] = field(default_factory=tuple)

    def display_instances_metadata(self) -> list[dict[str, Any]]:
        return [inst.to_metadata_dict() for inst in self.display_instances_order]

    def geometry_instances_metadata(self) -> list[dict[str, Any]]:
        return [inst.to_metadata_dict() for inst in self.sorted_instances_geometry_order]

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_uid": self.series_uid,
            "study_uid": self.study_uid,
            "modality": self.modality,
            "body_part": self.body_part,
            "laterality": self.laterality,
            "patient_position": self.patient_position,
            "plane": self.plane,
            "row_cosines": self.row_cosines,
            "col_cosines": self.col_cosines,
            "slice_normal": self.slice_normal,
            "sorted_instances_geometry_order": [inst.to_dict() for inst in self.sorted_instances_geometry_order],
            "display_instances_order": [inst.to_dict() for inst in self.display_instances_order],
            "dicom_files_for_itk": list(self.dicom_files_for_itk),
            "sop_uid_by_display_index": list(self.sop_uid_by_display_index),
            "ipp_by_display_index": list(self.ipp_by_display_index),
            "iop_by_display_index": list(self.iop_by_display_index),
            "display_order_hash": self.display_order_hash,
            "geometry_order_hash": self.geometry_order_hash,
            "first_display_label": self.first_display_label,
            "last_display_label": self.last_display_label,
            "display_convention": self.display_convention,
            "display_to_geometry_index": list(self.display_to_geometry_index),
            "geometry_to_display_index": list(self.geometry_to_display_index),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SeriesGeometryIndex":
        geometry = tuple(
            GeometryIndexedInstance.from_dict(inst)
            for inst in payload.get("sorted_instances_geometry_order") or []
        )
        display = tuple(
            GeometryIndexedInstance.from_dict(inst)
            for inst in payload.get("display_instances_order") or []
        )
        return cls(
            series_uid=str(payload.get("series_uid") or ""),
            study_uid=str(payload.get("study_uid") or ""),
            modality=str(payload.get("modality") or ""),
            body_part=str(payload.get("body_part") or ""),
            laterality=str(payload.get("laterality") or ""),
            patient_position=str(payload.get("patient_position") or ""),
            plane=str(payload.get("plane") or "OBLIQUE"),
            row_cosines=tuple(payload.get("row_cosines") or (0.0, 0.0, 0.0)),
            col_cosines=tuple(payload.get("col_cosines") or (0.0, 0.0, 0.0)),
            slice_normal=tuple(payload.get("slice_normal") or (0.0, 0.0, 0.0)),
            sorted_instances_geometry_order=geometry,
            display_instances_order=display,
            dicom_files_for_itk=tuple(payload.get("dicom_files_for_itk") or []),
            sop_uid_by_display_index=tuple(payload.get("sop_uid_by_display_index") or []),
            ipp_by_display_index=tuple(tuple(v) if v is not None else None for v in (payload.get("ipp_by_display_index") or [])),
            iop_by_display_index=tuple(tuple(v) if v is not None else None for v in (payload.get("iop_by_display_index") or [])),
            display_order_hash=str(payload.get("display_order_hash") or ""),
            geometry_order_hash=str(payload.get("geometry_order_hash") or ""),
            first_display_label=str(payload.get("first_display_label") or "?"),
            last_display_label=str(payload.get("last_display_label") or "?"),
            display_convention=str(payload.get("display_convention") or ""),
            display_to_geometry_index=tuple(int(v) for v in (payload.get("display_to_geometry_index") or [])),
            geometry_to_display_index=tuple(int(v) for v in (payload.get("geometry_to_display_index") or [])),
        )


def get_series_geometry_index(metadata: dict[str, Any] | None) -> SeriesGeometryIndex | None:
    if not isinstance(metadata, dict):
        return None
    obj = metadata.get("_series_geometry_index_obj")
    if isinstance(obj, SeriesGeometryIndex):
        return obj
    payload = metadata.get("series_geometry_index")
    if isinstance(payload, dict):
        try:
            obj = SeriesGeometryIndex.from_dict(payload)
            metadata["_series_geometry_index_obj"] = obj
            return obj
        except Exception:
            return None
    return None


def assert_advanced_order_contract(metadata: dict[str, Any] | None, *, caller: str) -> SeriesGeometryIndex | None:
    geometry_index = get_series_geometry_index(metadata)
    if geometry_index is None:
        return None
    current_hash = _metadata_path_hash(metadata.get("instances") or [])
    if current_hash != geometry_index.display_order_hash:
        logger.error(
            "[ADVANCED_ORDER_CONTRACT_ERROR] caller=%s current_hash=%s expected_hash=%s series_uid=%s",
            caller,
            current_hash,
            geometry_index.display_order_hash,
            geometry_index.series_uid,
            extra={"component": "viewer"},
        )
        raise RuntimeError(
            f"[ADVANCED_ORDER_CONTRACT_ERROR] caller={caller} current_hash={current_hash} expected_hash={geometry_index.display_order_hash}"
        )
    return geometry_index


def stamp_metadata_with_geometry_index(
    metadata: dict[str, Any],
    geometry_index: SeriesGeometryIndex,
) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["instances"] = geometry_index.display_instances_metadata()
    metadata["series_geometry_index"] = geometry_index.to_dict()
    metadata["_series_geometry_index_obj"] = geometry_index
    metadata["instances_order_contract"] = "ADVANCED_SERIES_GEOMETRY_INDEX"
    metadata["display_order_hash"] = geometry_index.display_order_hash
    metadata["canonical_order_hash"] = geometry_index.geometry_order_hash
    metadata["display_convention_applied"] = True
    metadata["_instances_geometry_sorted"] = True
    return metadata


def _read_minimal_header(path: str) -> dict[str, Any]:
    ds = utils._safe_dcmread(
        str(path),
        stop_before_pixels=True,
    )
    if ds is None:
        raise ValueError(f"Could not read DICOM header: {path}")

    raw_iop = ds.get("ImageOrientationPatient", None)
    raw_ipp = ds.get("ImagePositionPatient", None)
    raw_ps = ds.get("PixelSpacing", None)
    iop = tuple(float(v) for v in raw_iop) if raw_iop is not None and len(raw_iop) >= 6 else None
    ipp = tuple(float(v) for v in raw_ipp) if raw_ipp is not None and len(raw_ipp) >= 3 else None
    pixel_spacing = tuple(float(v) for v in raw_ps[:2]) if raw_ps is not None and len(raw_ps) >= 2 else None
    normal = _slice_normal_from_iop(iop)
    if normal is None or ipp is None:
        raise ValueError(f"Missing IPP/IOP for Advanced geometry contract: {path}")

    row = tuple(float(v) for v in iop[0:3])
    col = tuple(float(v) for v in iop[3:6])
    slice_pos = float(np.dot(np.asarray(ipp, dtype=float), normal))
    return {
        "instance_number": int(ds.get("InstanceNumber", 0) or 0),
        "instance_path": str(path),
        "rows": int(ds.get("Rows", 0) or 0),
        "columns": int(ds.get("Columns", 0) or 0),
        "window_width": ds.get("WindowWidth", None),
        "window_center": ds.get("WindowCenter", None),
        "is_rgb": str(ds.get("PhotometricInterpretation", "")).upper() in {"RGB", "YBR_FULL", "YBR_FULL_422"},
        "sop_uid": str(ds.get("SOPInstanceUID", "") or ""),
        "image_orientation_patient": iop,
        "image_position_patient": ipp,
        "pixel_spacing": pixel_spacing,
        "slice_thickness": float(ds.get("SliceThickness", 0.0) or 0.0) if ds.get("SliceThickness", None) is not None else None,
        "spacing_between_slices": float(ds.get("SpacingBetweenSlices", 0.0) or 0.0) if ds.get("SpacingBetweenSlices", None) is not None else None,
        "rescale_slope": float(ds.get("RescaleSlope", 1.0) or 1.0),
        "rescale_intercept": float(ds.get("RescaleIntercept", 0.0) or 0.0),
        "bits_allocated": int(ds.get("BitsAllocated", 16) or 16),
        "pixel_representation": int(ds.get("PixelRepresentation", 1) or 1),
        "study_uid": str(ds.get("StudyInstanceUID", "") or ""),
        "series_uid": str(ds.get("SeriesInstanceUID", "") or ""),
        "series_number": str(ds.get("SeriesNumber", "") or ""),
        "modality": str(ds.get("Modality", "") or ""),
        "body_part": str(ds.get("BodyPartExamined", "") or ""),
        "laterality": str(ds.get("Laterality", "") or ""),
        "patient_position": str(ds.get("PatientPosition", "") or ""),
        "series_description": str(ds.get("SeriesDescription", "") or ""),
        "protocol_name": str(ds.get("ProtocolName", "") or ""),
        "row_cosines": row,
        "col_cosines": col,
        "slice_normal": tuple(float(v) for v in normal.tolist()),
        "slice_pos": slice_pos,
    }


def build_series_geometry_index(
    dicom_files: list[str] | tuple[str, ...],
    *,
    patient_code: str = "",
    study_uid_hint: str = "",
    series_uid_hint: str = "",
    series_number_hint: str = "",
    source: str = "fresh_files",
    cache_payload: dict[str, Any] | None = None,
) -> tuple[SeriesGeometryIndex, bool]:
    normalized_input = [str(path) for path in (dicom_files or []) if str(path or "").strip()]
    if not normalized_input:
        raise ValueError("No DICOM files available for Advanced geometry contract")

    if isinstance(cache_payload, dict):
        cached_index = SeriesGeometryIndex.from_dict(cache_payload)
        logger.warning(
            "[ADVANCED_SERIES_GEOMETRY_INDEX] patient_code=%s study_uid=%s series_uid=%s series_number=%s "
            "n_instances=%d plane=%s modality=%s body_part=%s laterality=%s patient_position=%s "
            "row_cosines=%s col_cosines=%s slice_normal=%s geometry_order_hash=%s display_order_hash=%s "
            "display_convention=%s first_display_sop_uid=%s last_display_sop_uid=%s first_display_ipp=%s last_display_ipp=%s "
            "first_display_label=%s last_display_label=%s source=cache cache_hit=True",
            patient_code,
            cached_index.study_uid,
            cached_index.series_uid,
            series_number_hint or (cached_index.display_instances_order[0].series_number if cached_index.display_instances_order else ""),
            len(cached_index.display_instances_order),
            cached_index.plane,
            cached_index.modality,
            cached_index.body_part,
            cached_index.laterality,
            cached_index.patient_position,
            cached_index.row_cosines,
            cached_index.col_cosines,
            cached_index.slice_normal,
            cached_index.geometry_order_hash,
            cached_index.display_order_hash,
            cached_index.display_convention,
            cached_index.sop_uid_by_display_index[0] if cached_index.sop_uid_by_display_index else "",
            cached_index.sop_uid_by_display_index[-1] if cached_index.sop_uid_by_display_index else "",
            cached_index.ipp_by_display_index[0] if cached_index.ipp_by_display_index else None,
            cached_index.ipp_by_display_index[-1] if cached_index.ipp_by_display_index else None,
            cached_index.first_display_label,
            cached_index.last_display_label,
            extra={"component": "viewer"},
        )
        return cached_index, True

    headers = [_read_minimal_header(path) for path in normalized_input]
    series_uid_set = {header["series_uid"] for header in headers if header.get("series_uid")}
    if series_uid_hint:
        series_uid_set.add(str(series_uid_hint))
    if len(series_uid_set) != 1:
        logger.error(
            "[ADVANCED_ORDER_CONTRACT_ERROR] reason=mixed_series_uid series_uid_set=%s source=%s",
            sorted(series_uid_set),
            source,
            extra={"component": "viewer"},
        )
        raise ValueError(f"Mixed SeriesInstanceUID in Advanced geometry contract: {sorted(series_uid_set)}")

    study_uid_set = {header["study_uid"] for header in headers if header.get("study_uid")}
    if study_uid_hint:
        study_uid_set.add(str(study_uid_hint))

    row_cosines = headers[0]["row_cosines"]
    col_cosines = headers[0]["col_cosines"]
    slice_normal = headers[0]["slice_normal"]
    plane, dominant_axis, dominance_value = _plane_from_normal(np.asarray(slice_normal, dtype=float))

    angle_deviations: list[float] = []
    plane_set: set[str] = set()
    for header in headers:
        nrm = np.asarray(header["slice_normal"], dtype=float)
        base = np.asarray(slice_normal, dtype=float)
        dot = float(np.clip(np.dot(nrm, base), -1.0, 1.0))
        angle_deviations.append(math.degrees(math.acos(dot)))
        header_plane, _, _ = _plane_from_normal(nrm)
        plane_set.add(header_plane)

    if len(plane_set) > 1 or (angle_deviations and max(angle_deviations) > 10.0):
        logger.warning(
            "[ADVANCED_SERIES_GEOMETRY_WARNING] reason=mixed_plane_or_orientation series_uid=%s plane_set=%s max_angle_deg=%.3f",
            headers[0]["series_uid"],
            sorted(plane_set),
            max(angle_deviations) if angle_deviations else 0.0,
            extra={"component": "viewer"},
        )

    geometry_sorted_headers = sorted(
        headers,
        key=lambda header: (
            float(header["slice_pos"]),
            int(header["instance_number"]),
            str(header["sop_uid"]),
            str(header["instance_path"]),
        ),
    )

    geometry_instances = tuple(
        GeometryIndexedInstance(
            instance_number=int(header["instance_number"]),
            instance_path=str(header["instance_path"]),
            rows=int(header["rows"]),
            columns=int(header["columns"]),
            window_width=header.get("window_width"),
            window_center=header.get("window_center"),
            is_rgb=bool(header["is_rgb"]),
            sop_uid=str(header["sop_uid"]),
            image_orientation_patient=tuple(header["image_orientation_patient"]) if header.get("image_orientation_patient") is not None else None,
            image_position_patient=tuple(header["image_position_patient"]) if header.get("image_position_patient") is not None else None,
            pixel_spacing=tuple(header["pixel_spacing"]) if header.get("pixel_spacing") is not None else None,
            slice_thickness=header.get("slice_thickness"),
            spacing_between_slices=header.get("spacing_between_slices"),
            rescale_slope=float(header.get("rescale_slope") or 1.0),
            rescale_intercept=float(header.get("rescale_intercept") or 0.0),
            bits_allocated=int(header.get("bits_allocated") or 16),
            pixel_representation=int(header.get("pixel_representation") or 1),
            study_uid=str(next(iter(study_uid_set)) if study_uid_set else ""),
            series_uid=str(next(iter(series_uid_set))),
            series_number=str(header.get("series_number") or series_number_hint or ""),
            slice_pos=float(header["slice_pos"]),
        )
        for header in geometry_sorted_headers
    )

    geometry_first_ipp = geometry_instances[0].image_position_patient if geometry_instances else None
    geometry_last_ipp = geometry_instances[-1].image_position_patient if geometry_instances else None
    geometry_first_label, geometry_last_label = _label_pair_from_ipps(
        geometry_first_ipp,
        geometry_last_ipp,
        dominant_axis,
    )
    raw_body_part = headers[0].get("body_part") or ""
    raw_laterality = headers[0].get("laterality") or ""
    series_description = headers[0].get("series_description") or ""
    protocol_name = headers[0].get("protocol_name") or ""
    normalized_body_part = _normalize_body_part_canonical(raw_body_part)
    normalized_laterality = _normalize_laterality(raw_laterality)

    desired_first_label, desired_last_label, sort_target_first_label, display_convention, unresolved, axial_like_info = _resolve_display_labels(
        plane=plane,
        body_part=raw_body_part,
        patient_position=headers[0].get("patient_position") or "",
        geometry_first_label=geometry_first_label,
        geometry_last_label=geometry_last_label,
        dominant_axis=dominant_axis,
        dominance_value=dominance_value,
        series_description=series_description,
        protocol_name=protocol_name,
    )

    display_instances = geometry_instances
    applied_reverse = False
    if sort_target_first_label == "Z_SUPERIOR":
        # Non-Z-dominant AXIAL_LIKE_EXTREMITY: use Z-component of IPP for proximal direction.
        # Higher Z (more Superior) = more proximal (toward trunk) for all extremity orientations.
        first_z = geometry_instances[0].image_position_patient[2] if geometry_instances[0].image_position_patient else None
        last_z = geometry_instances[-1].image_position_patient[2] if geometry_instances[-1].image_position_patient else None
        if first_z is not None and last_z is not None and not math.isclose(first_z, last_z, abs_tol=1.0):
            if first_z < last_z:
                # First slice is more inferior (distal) → reverse to put proximal first.
                display_instances = tuple(reversed(geometry_instances))
                applied_reverse = True
    else:
        if geometry_first_label != sort_target_first_label and geometry_last_label == sort_target_first_label:
            display_instances = tuple(reversed(geometry_instances))
            applied_reverse = True

    display_to_geometry_index = tuple(
        geometry_instances.index(inst)
        for inst in display_instances
    )
    geometry_to_display_lookup = {geom_idx: disp_idx for disp_idx, geom_idx in enumerate(display_to_geometry_index)}
    geometry_to_display_index = tuple(geometry_to_display_lookup[idx] for idx in range(len(display_instances)))

    first_display_ipp = display_instances[0].image_position_patient if display_instances else None
    last_display_ipp = display_instances[-1].image_position_patient if display_instances else None
    first_display_label, last_display_label = _label_pair_from_ipps(
        first_display_ipp,
        last_display_ipp,
        dominant_axis,
    )
    if desired_first_label == "Proximal":
        # For AXIAL_LIKE_EXTREMITY: always override to Proximal/Distal regardless of axis labels.
        # The reversal logic above already positioned the instances anatomically.
        first_display_label = "Proximal"
        last_display_label = "Distal"

    series_geometry_index = SeriesGeometryIndex(
        series_uid=str(next(iter(series_uid_set))),
        study_uid=str(next(iter(study_uid_set)) if study_uid_set else ""),
        modality=str(headers[0].get("modality") or ""),
        body_part=str(headers[0].get("body_part") or ""),
        laterality=str(headers[0].get("laterality") or ""),
        patient_position=str(headers[0].get("patient_position") or ""),
        plane=plane,
        row_cosines=tuple(float(v) for v in row_cosines),
        col_cosines=tuple(float(v) for v in col_cosines),
        slice_normal=tuple(float(v) for v in slice_normal),
        sorted_instances_geometry_order=geometry_instances,
        display_instances_order=display_instances,
        dicom_files_for_itk=tuple(inst.instance_path for inst in display_instances),
        sop_uid_by_display_index=tuple(inst.sop_uid for inst in display_instances),
        ipp_by_display_index=tuple(inst.image_position_patient for inst in display_instances),
        iop_by_display_index=tuple(inst.image_orientation_patient for inst in display_instances),
        display_order_hash=_hash_paths([inst.instance_path for inst in display_instances]),
        geometry_order_hash=_hash_paths([inst.instance_path for inst in geometry_instances]),
        first_display_label=first_display_label,
        last_display_label=last_display_label,
        display_convention=display_convention,
        display_to_geometry_index=display_to_geometry_index,
        geometry_to_display_index=geometry_to_display_index,
    )

    if unresolved:
        logger.warning(
            "[ADVANCED_SERIES_GEOMETRY_WARNING] reason=unresolved_extremity_display series_uid=%s body_part=%s patient_position=%s",
            series_geometry_index.series_uid,
            series_geometry_index.body_part,
            series_geometry_index.patient_position,
            extra={"component": "viewer"},
        )

    if axial_like_info[0]:
        logger.warning(
            "[ADVANCED_AXIAL_LIKE_EXTREMITY] patient_code=%s series_uid=%s series_number=%s "
            "raw_body_part=%s normalized_body_part=%s raw_laterality=%s normalized_laterality=%s "
            "series_description=%s protocol_name=%s "
            "original_plane=%s reason=%s confidence=%s "
            "dominant_axis=%s dominance=%.4f "
            "geometry_first_label=%s geometry_last_label=%s "
            "first_label_after=%s last_label_after=%s applied_reverse=%s",
            patient_code,
            series_geometry_index.series_uid,
            series_number_hint or (display_instances[0].series_number if display_instances else ""),
            raw_body_part, normalized_body_part,
            raw_laterality, normalized_laterality,
            series_description, protocol_name,
            plane, axial_like_info[1], axial_like_info[2],
            dominant_axis, dominance_value,
            geometry_first_label, geometry_last_label,
            series_geometry_index.first_display_label,
            series_geometry_index.last_display_label,
            applied_reverse,
            extra={"component": "viewer"},
        )

    logger.warning(
        "[ADVANCED_SERIES_GEOMETRY_INDEX] patient_code=%s study_uid=%s series_uid=%s series_number=%s "
        "n_instances=%d plane=%s modality=%s body_part=%s laterality=%s patient_position=%s row_cosines=%s "
        "col_cosines=%s slice_normal=%s geometry_order_hash=%s display_order_hash=%s display_convention=%s "
        "first_display_sop_uid=%s last_display_sop_uid=%s first_display_ipp=%s last_display_ipp=%s "
        "first_display_label=%s last_display_label=%s source=%s cache_hit=False",
        patient_code,
        series_geometry_index.study_uid,
        series_geometry_index.series_uid,
        series_number_hint or (display_instances[0].series_number if display_instances else ""),
        len(display_instances),
        series_geometry_index.plane,
        series_geometry_index.modality,
        series_geometry_index.body_part,
        series_geometry_index.laterality,
        series_geometry_index.patient_position,
        series_geometry_index.row_cosines,
        series_geometry_index.col_cosines,
        series_geometry_index.slice_normal,
        series_geometry_index.geometry_order_hash,
        series_geometry_index.display_order_hash,
        series_geometry_index.display_convention,
        series_geometry_index.sop_uid_by_display_index[0] if series_geometry_index.sop_uid_by_display_index else "",
        series_geometry_index.sop_uid_by_display_index[-1] if series_geometry_index.sop_uid_by_display_index else "",
        series_geometry_index.ipp_by_display_index[0] if series_geometry_index.ipp_by_display_index else None,
        series_geometry_index.ipp_by_display_index[-1] if series_geometry_index.ipp_by_display_index else None,
        series_geometry_index.first_display_label,
        series_geometry_index.last_display_label,
        source,
        extra={"component": "viewer"},
    )

    return series_geometry_index, False