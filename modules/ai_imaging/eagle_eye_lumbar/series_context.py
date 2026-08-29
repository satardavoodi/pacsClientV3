"""Sanitize PACS series metadata for the Eagle Eye context branch.

The capture engine calls one public function and remains protocol-agnostic.
This module owns descriptive metadata classification and never retains series
UIDs, patient identity, or local paths.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


_INVENTORY_LIMIT = 512
_PLANES = {"axial", "coronal", "sagittal", "unknown"}
_CONTRAST_EVIDENCE = {"none", "precontrast", "postcontrast"}
_KINDS = {"clinical_document", "imaging"}


def _value(series: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = series.get(key)
        if value not in (None, ""):
            return " ".join(str(value).split())
    return ""


def _plane(series: Dict[str, Any]) -> str:
    text = " ".join((
        _value(series, "series_description", "SeriesDescription"),
        _value(series, "protocol_name", "ProtocolName"),
        _value(series, "image_type", "ImageType"),
    )).lower()
    for plane, tokens in (
        ("sagittal", ("sagittal", " sag ", "_sag", " sag_")),
        ("axial", ("axial", "transverse", " tra ", "_tra")),
        ("coronal", ("coronal", " cor ", "_cor")),
    ):
        if any(token in f" {text} " for token in tokens):
            return plane
    return "unknown"


def _contrast_evidence(series: Dict[str, Any]) -> str:
    contrast_agent = _value(
        series,
        "contrast_bolus_agent",
        "ContrastBolusAgent",
    )
    text = " ".join((
        _value(series, "series_description", "SeriesDescription"),
        _value(series, "protocol_name", "ProtocolName"),
        _value(series, "image_type", "ImageType"),
    )).lower()
    normalized = re.sub(r"[^a-z0-9+]+", " ", text)
    post_tokens = (
        "post contrast",
        "postcontrast",
        "post gad",
        "postgad",
        "t1 fs c+",
        "t1 fat sat c+",
        "enhanced",
    )
    if contrast_agent or any(
        token in normalized or token in text for token in post_tokens
    ):
        return "postcontrast"
    if any(
        token in normalized
        for token in ("pre contrast", "precontrast", "non contrast")
    ):
        return "precontrast"
    return "none"


def _entry(series: Dict[str, Any], instances: Any) -> Dict[str, Any]:
    series_number = _value(series, "series_number", "SeriesNumber")
    modality = _value(series, "modality", "Modality").upper()
    description = _value(
        series,
        "series_description",
        "SeriesDescription",
    )
    protocol = _value(series, "protocol_name", "ProtocolName")
    body_part = _value(
        series,
        "body_part",
        "body_part_examined",
        "BodyPartExamined",
    )
    try:
        slice_count = len(instances or ())
    except TypeError:
        slice_count = 0
    is_document = series_number == "100000" or (
        modality in {"DOC", "OT"}
        and (
            "history" in description.lower()
            or "document" in description.lower()
        )
    )
    return {
        "series_number": series_number,
        "modality": modality,
        "description": description,
        "protocol": protocol,
        "body_part": body_part,
        "plane": _plane(series),
        "slice_count": slice_count,
        "contrast_evidence": _contrast_evidence(series),
        "kind": "clinical_document" if is_document else "imaging",
    }


def sanitize_series_inventory(items: Any) -> List[Dict[str, Any]]:
    """Return the bounded, identity-free series inventory contract."""
    if not isinstance(items, (list, tuple)):
        return []

    inventory: List[Dict[str, Any]] = []
    for item in items[:_INVENTORY_LIMIT]:
        if not isinstance(item, dict):
            continue
        try:
            slice_count = max(0, int(item.get("slice_count") or 0))
        except (TypeError, ValueError):
            slice_count = 0
        plane = str(item.get("plane") or "unknown").strip().lower()
        contrast = str(item.get("contrast_evidence") or "none").strip().lower()
        kind = str(item.get("kind") or "imaging").strip().lower()
        inventory.append({
            "series_number": " ".join(str(item.get("series_number") or "").split()),
            "modality": " ".join(str(item.get("modality") or "").split()).upper(),
            "description": " ".join(str(item.get("description") or "").split()),
            "protocol": " ".join(str(item.get("protocol") or "").split()),
            "body_part": " ".join(str(item.get("body_part") or "").split()),
            "plane": plane if plane in _PLANES else "unknown",
            "slice_count": slice_count,
            "contrast_evidence": (
                contrast if contrast in _CONTRAST_EVIDENCE else "none"
            ),
            "kind": kind if kind in _KINDS else "imaging",
        })
    return inventory


def _candidate_entry(candidate: Any) -> Dict[str, Any]:
    series = {
        "series_number": getattr(candidate, "series_number", ""),
        "modality": getattr(candidate, "modality", ""),
        "series_description": getattr(candidate, "series_description", ""),
        "protocol_name": getattr(candidate, "protocol_name", ""),
        "body_part": getattr(candidate, "body_part", ""),
        "image_type": getattr(candidate, "image_type", ""),
    }
    entry = _entry(series, getattr(candidate, "instances", ()) or ())
    try:
        entry["slice_count"] = max(0, int(getattr(candidate, "slice_count", 0) or 0))
    except (TypeError, ValueError):
        pass
    plane = str(getattr(candidate, "plane", "") or "").strip().lower()
    if plane in _PLANES:
        entry["plane"] = plane
    return entry


def snapshot_series_catalog(
    patient_widget: Any,
    selection: Any,
    candidates: Any = None,
) -> tuple[str, List[Dict[str, Any]]]:
    """Snapshot the loaded PACS catalogue without UIDs or identity."""
    thumbnails = list(getattr(patient_widget, "lst_thumbnails_data", []) or [])
    inventory: List[Dict[str, Any]] = []
    for thumbnail in thumbnails:
        metadata = (
            (thumbnail or {}).get("metadata", {})
            if isinstance(thumbnail, dict)
            else {}
        )
        series = (
            (metadata or {}).get("series", {})
            if isinstance(metadata, dict)
            else {}
        )
        instances = (
            (metadata or {}).get("instances", ())
            if isinstance(metadata, dict)
            else ()
        )
        if isinstance(series, dict) and series:
            inventory.append(_entry(series, instances))
    probed_inventory = [
        _candidate_entry(candidate)
        for candidate in list(candidates or ())[:_INVENTORY_LIMIT]
        if candidate is not None
    ]
    if probed_inventory and len(probed_inventory) > len(inventory):
        inventory = probed_inventory
    if inventory:
        return "pacs_series_catalog", sanitize_series_inventory(inventory)

    seen = set()
    for slot in (
        getattr(selection, "slot_order", None)
        or getattr(getattr(selection, "protocol", None), "slot_keys", ())
    ):
        candidate = selection.candidate_for(slot)
        if candidate is None:
            continue
        key = str(getattr(candidate, "series_number", "") or "")
        if key in seen:
            continue
        seen.add(key)
        inventory.append(_candidate_entry(candidate))
    return "locally_available_series_only", sanitize_series_inventory(inventory)
