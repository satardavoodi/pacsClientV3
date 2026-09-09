"""Build anatomy-only cards between source mapping and pathology screening.

The workstation first creates neutral geometry groups. The mapping model assigns
sequence and anatomical meaning without assessing normality. Local code validates
every proposed atlas tile against the immutable geometry groups, preserves its
DICOM mapping record, and renders five task-specific screening cards.
"""

from __future__ import annotations

import json
import math
from itertools import zip_longest
from pathlib import Path
from typing import Any, Dict

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from modules.ai_imaging.eagle_eye.card_templates import (
    get_card_template,
    list_card_templates,
)

from .focus_evidence import _atomic_image, _atomic_json
from .llm_package import AnalysisPackage, PackagedImage


ANATOMY_CARD_MODE = "anatomy-gate-v4"
ANATOMY_CARD_SCHEMA_VERSION = "1.10.0"
ANATOMY_CARD_MANIFEST = "anatomy_manifest.json"
STANDARD_LEVELS = ("T12-L1", "L1-L2", "L2-L3", "L3-L4", "L4-L5", "L5-S1")
# Mapping may cover more anatomy than this lumbar diagnostic pipeline supports.
# These labels are retained as context, never converted into lumbar diagnoses.
CONTEXT_LEVELS = tuple(f"T{index}-T{index + 1}" for index in range(1, 12)) + ("S1-S2",)
ANATOMICAL_LEVEL_ORDER = CONTEXT_LEVELS[:-1] + STANDARD_LEVELS + CONTEXT_LEVELS[-1:]
SAGITTAL_PLANES = (
    "right_foraminal",
    "right_paracentral",
    "midline",
    "left_paracentral",
    "left_foraminal",
)
AXIAL_PLANES = ("disc_level", "subarticular", "infrapedicular")
SAGITTAL_GROUP_ROLES = ("right_lateral", "central", "left_lateral")
SAGITTAL_PLANE_GROUP_ROLE = {
    "right_foraminal": "right_lateral",
    "right_paracentral": "central",
    "midline": "central",
    "left_paracentral": "central",
    "left_foraminal": "left_lateral",
}
_GEOMETRY_GROUP_COLORS = {
    "right_lateral": "#38bdf8",
    "central": "#a78bfa",
    "left_lateral": "#34d399",
}
CARD_HEADER_HEIGHT = 68
CARD_BLOCK_HEADER = 26
CARD_GROUP_GAP = 32
CARD_SECTION_GAP = 44


class AnatomyCardError(RuntimeError):
    """An anatomy map or card could not be used without guessing."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = str(code or "anatomy_card_failed")


def _atlas_entries(package: AnalysisPackage) -> Dict[str, tuple[dict, dict, int]]:
    entries: Dict[str, tuple[dict, dict, int]] = {}
    for page in package.evidence_audit.get("pages", ()):
        if not isinstance(page, dict):
            continue
        for position, tile in enumerate(page.get("tiles", ())):
            if not isinstance(tile, dict):
                continue
            tile_id = str(tile.get("tile_id") or "")
            if not tile_id or tile_id in entries:
                raise AnatomyCardError(
                    "anatomy_atlas_identity_conflict",
                    "The screening atlas contains a missing or duplicate tile identity.",
                )
            entries[tile_id] = (page, tile, position)
    if not entries:
        raise AnatomyCardError(
            "anatomy_atlas_inventory_missing",
            "The screening atlas has no auditable tile inventory.",
        )
    return entries


def _tile_role(entries: Dict[str, tuple[dict, dict, int]], tile_id: Any) -> str:
    entry = entries.get(str(tile_id or ""))
    return str(entry[1].get("role") or "") if entry else ""


def _tile_series_id(entries: Dict[str, tuple[dict, dict, int]], tile_id: Any) -> str:
    entry = entries.get(str(tile_id or ""))
    if not entry:
        return ""
    tile = entry[1]
    return str(tile.get("series_id") or tile.get("role") or "")


def _series_contract(package: AnalysisPackage) -> dict[str, dict[str, Any]]:
    raw = package.evidence_audit.get("series_contract")
    if isinstance(raw, dict) and raw:
        return {
            str(series_id): dict(record)
            for series_id, record in raw.items()
            if series_id and isinstance(record, dict)
        }
    # Read-only compatibility for pre-1.3 saved atlases. New atlases always
    # publish neutral series IDs and confidence-aware semantic metadata.
    return {
        "sagittal_t2": {"plane": "sagittal", "semantic_label": "sagittal_t2"},
        "sagittal_t1": {"plane": "sagittal", "semantic_label": "sagittal_t1"},
        "axial_t2": {"plane": "axial", "semantic_label": "axial_t2"},
    }


def _axial_groups(package: AnalysisPackage) -> dict[str, tuple[int, int]]:
    geometry = package.evidence_audit.get("geometry_groups")
    rows = geometry.get("axial") if isinstance(geometry, dict) else None
    result: dict[str, tuple[int, int]] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            group_id = str(row.get("group_id") or "")
            bounds = row.get("axial_frames")
            try:
                first, last = int(bounds[0]), int(bounds[1])
            except (IndexError, TypeError, ValueError):
                continue
            if group_id and first > 0 and last >= first:
                result[group_id] = (first, last)
    if result:
        return result
    return {
        f"axial-group-{index:02d}": tuple(map(int, bounds))
        for index, bounds in enumerate(
            package.evidence_audit.get("measured_slabs", ()), start=1
        )
        if isinstance(bounds, (list, tuple)) and len(bounds) == 2
    }


def _sagittal_groups(package: AnalysisPackage) -> dict[str, dict[str, Any]]:
    geometry = package.evidence_audit.get("geometry_groups")
    rows = geometry.get("sagittal") if isinstance(geometry, dict) else None
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        group_id = str(row.get("group_id") or "")
        members = row.get("series_members")
        if not group_id or not isinstance(members, dict):
            continue
        result[group_id] = {
            "spatial_order": int(row.get("spatial_order") or 0),
            "series_members": {
                str(series_id): {
                    "source_slices": tuple(
                        int(value)
                        for value in record.get("source_slices", ())
                        if type(value) is int and value > 0
                    )
                }
                for series_id, record in members.items()
                if series_id and isinstance(record, dict)
            },
        }
    return result


def _plane_coordinate(tile: dict) -> float:
    mapping = tile.get("mapping")
    if not isinstance(mapping, dict) or mapping.get("kind") != "volume":
        raise AnatomyCardError(
            "anatomy_map_geometry_missing",
            "A sagittal anatomy tile has no validated volume geometry.",
        )
    try:
        direction = np.asarray(mapping["direction"], dtype=float).reshape(3, 3)
        origin = np.asarray(mapping["origin"], dtype=float)
        spacing = np.asarray(mapping["spacing"], dtype=float)
        index = int(mapping["slice_index"])
        point = origin + direction[:, 2] * spacing[2] * index
    except (KeyError, TypeError, ValueError) as exc:
        raise AnatomyCardError(
            "anatomy_map_geometry_invalid",
            "A sagittal anatomy tile contains invalid volume geometry.",
        ) from exc
    if not np.isfinite(point).all():
        raise AnatomyCardError(
            "anatomy_map_geometry_invalid",
            "A sagittal anatomy tile contains non-finite geometry.",
        )
    # DICOM LPS X increases toward patient left. This remains valid for a
    # mildly oblique sagittal acquisition and avoids trusting file order.
    return float(point[0])


def _axial_superior_coordinate(tile: dict) -> float:
    mapping = tile.get("mapping")
    if not isinstance(mapping, dict) or mapping.get("kind") != "dicom_slice":
        raise AnatomyCardError(
            "anatomy_map_geometry_missing",
            "An axial anatomy tile has no validated DICOM geometry.",
        )
    try:
        position = np.asarray(mapping["position_lps"], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise AnatomyCardError(
            "anatomy_map_geometry_invalid",
            "An axial anatomy tile contains invalid patient-space geometry.",
        ) from exc
    if position.shape != (3,) or not np.isfinite(position).all():
        raise AnatomyCardError(
            "anatomy_map_geometry_invalid",
            "An axial anatomy tile contains non-finite patient-space geometry.",
        )
    # DICOM LPS Z increases toward the patient's head. Sorting by descending Z
    # therefore gives the anatomical superior-to-inferior order regardless of
    # file, instance-number, source-volume, or capture-frame ordering.
    return float(position[2])


def normalize_anatomy_map(
    package: AnalysisPackage, structured: Any,
) -> dict[str, Any]:
    """Validate model semantics against workstation-owned geometry groups."""
    if not isinstance(structured, dict):
        raise AnatomyCardError("anatomy_map_unstructured", "The anatomy map is not JSON.")
    if str(structured.get("schema_version") or "") not in ("1.8.0", "1.9.0", ANATOMY_CARD_SCHEMA_VERSION):
        raise AnatomyCardError(
            "anatomy_map_schema_conflict",
            "The anatomy map does not use the active anatomy-card schema.",
        )
    entries = _atlas_entries(package)
    series_contract = _series_contract(package)
    raw_assignments = structured.get("sequence_assignments")
    if not isinstance(raw_assignments, dict):
        raise AnatomyCardError(
            "anatomy_map_sequence_assignments_missing",
            "The anatomy map has no neutral-series sequence assignments.",
        )
    sequence_assignments: dict[str, dict[str, str]] = {}
    used_series: set[str] = set()
    for semantic_role, expected_plane in (
        ("sagittal_t2", "sagittal"),
        ("sagittal_t1", "sagittal"),
        ("axial_t2", "axial"),
    ):
        proposed = raw_assignments.get(semantic_role)
        if not isinstance(proposed, dict):
            raise AnatomyCardError(
                "anatomy_map_sequence_assignments_missing",
                f"The anatomy map has no {semantic_role} series assignment.",
            )
        series_id = str(proposed.get("series_id") or "")
        confidence = str(proposed.get("confidence") or "").strip().casefold()
        contract = series_contract.get(series_id)
        if contract is None or str(contract.get("plane") or "") != expected_plane:
            raise AnatomyCardError(
                "anatomy_map_sequence_assignment_conflict",
                f"The {semantic_role} assignment does not reference a compatible neutral series.",
            )
        if series_id in used_series:
            raise AnatomyCardError(
                "anatomy_map_duplicate_sequence_assignment",
                "One neutral series cannot fill multiple sequence roles.",
            )
        if confidence not in {"high", "moderate", "low"}:
            raise AnatomyCardError(
                "anatomy_map_sequence_confidence_invalid",
                f"The {semantic_role} assignment has no valid confidence.",
            )
        high_label = str(contract.get("semantic_label") or "")
        high_confidence = str(contract.get("semantic_confidence") or "").casefold() == "high"
        if high_label and high_confidence and high_label != semantic_role:
            raise AnatomyCardError(
                "anatomy_map_high_confidence_sequence_conflict",
                f"The {semantic_role} assignment conflicts with high-confidence metadata.",
            )
        used_series.add(series_id)
        sequence_assignments[semantic_role] = {
            "series_id": series_id,
            "confidence": confidence,
        }

    sagittal_groups = _sagittal_groups(package)
    raw_group_assignments = structured.get("sagittal_group_assignments")
    if not sagittal_groups:
        raise AnatomyCardError(
            "anatomy_map_sagittal_groups_missing",
            "The workstation did not establish neutral sagittal geometry groups.",
        )
    if (
        not isinstance(raw_group_assignments, list)
        or len(raw_group_assignments) != len(sagittal_groups)
    ):
        raise AnatomyCardError(
            "anatomy_map_sagittal_group_count_conflict",
            "The anatomy map must bind every neutral sagittal group exactly once.",
        )
    group_assignments: list[dict[str, str]] = []
    group_for_role: dict[str, str] = {}
    seen_sagittal_groups: set[str] = set()
    for raw_assignment in raw_group_assignments:
        if not isinstance(raw_assignment, dict):
            raise AnatomyCardError(
                "anatomy_map_sagittal_group_invalid",
                "A sagittal group assignment is not an object.",
            )
        group_id = str(raw_assignment.get("group_id") or "")
        anatomical_role = str(raw_assignment.get("anatomical_role") or "")
        confidence = str(raw_assignment.get("confidence") or "").strip().casefold()
        if group_id not in sagittal_groups or group_id in seen_sagittal_groups:
            raise AnatomyCardError(
                "anatomy_map_sagittal_group_identity_conflict",
                "A sagittal group identity is unknown or repeated.",
            )
        if anatomical_role not in SAGITTAL_GROUP_ROLES or anatomical_role in group_for_role:
            raise AnatomyCardError(
                "anatomy_map_sagittal_group_role_conflict",
                "A sagittal anatomical group role is unknown or repeated.",
            )
        if confidence not in {"high", "moderate", "low"}:
            raise AnatomyCardError(
                "anatomy_map_sagittal_group_confidence_invalid",
                "A sagittal group assignment has no valid confidence.",
            )
        seen_sagittal_groups.add(group_id)
        group_for_role[anatomical_role] = group_id
        group_assignments.append({
            "group_id": group_id,
            "anatomical_role": anatomical_role,
            "confidence": confidence,
        })
    group_assignments.sort(
        key=lambda row: int(sagittal_groups[row["group_id"]]["spatial_order"])
    )

    raw_sagittal = structured.get("sagittal_planes")
    if not isinstance(raw_sagittal, dict):
        raise AnatomyCardError(
            "anatomy_map_sagittal_missing", "The anatomy map has no sagittal plane map."
        )
    sagittal: dict[str, dict[str, str]] = {}
    canonicalization: dict[str, dict[str, Any]] = {}
    for role in ("sagittal_t2", "sagittal_t1"):
        proposed = raw_sagittal.get(role)
        if not isinstance(proposed, dict):
            raise AnatomyCardError(
                "anatomy_map_sagittal_missing", f"The anatomy map has no {role} plane map."
            )
        proposed_by_plane: dict[str, str] = {}
        for plane in SAGITTAL_PLANES:
            tile_id = str(proposed.get(plane) or "")
            if _tile_series_id(entries, tile_id) != sequence_assignments[role]["series_id"]:
                raise AnatomyCardError(
                    "anatomy_map_role_conflict",
                    f"The {plane} slot does not reference the series assigned to {role}.",
                )
            tile = entries[tile_id][1]
            group_id = str(tile.get("geometry_group_id") or "")
            expected_group = group_for_role[SAGITTAL_PLANE_GROUP_ROLE[plane]]
            if group_id != expected_group:
                raise AnatomyCardError(
                    "anatomy_map_sagittal_group_membership_conflict",
                    f"The {plane} slot does not belong to its assigned sagittal geometry group.",
                )
            member = sagittal_groups[group_id]["series_members"].get(
                sequence_assignments[role]["series_id"]
            )
            if (
                not isinstance(member, dict)
                or int(tile.get("source_slice") or 0) not in member["source_slices"]
            ):
                raise AnatomyCardError(
                    "anatomy_map_sagittal_group_membership_conflict",
                    f"The {plane} source slice is outside its immutable group membership.",
                )
            proposed_by_plane[plane] = tile_id
        selected_ids = list(proposed_by_plane.values())
        if len(set(selected_ids)) != len(SAGITTAL_PLANES):
            raise AnatomyCardError(
                "anatomy_map_duplicate_sagittal_plane",
                f"The {role} plane map reuses a source slice.",
            )
        ordered_ids = sorted(
            selected_ids,
            key=lambda tile_id: _plane_coordinate(entries[tile_id][1]),
        )
        coordinates = [_plane_coordinate(entries[tile_id][1]) for tile_id in ordered_ids]
        if any(b - a < 0.1 for a, b in zip(coordinates, coordinates[1:])) or ordered_ids[2] != proposed_by_plane["midline"]:
            raise AnatomyCardError(
                "anatomy_map_sagittal_side_ambiguous",
                "Physical side ordering cannot preserve the selected midline unambiguously.",
            )
        selected = dict(zip(SAGITTAL_PLANES, ordered_ids))
        # Correct semantic side labels only; keep source pixels, membership and level IDs.
        corrected_groups = {
            SAGITTAL_PLANE_GROUP_ROLE[plane]: str(entries[tile_id][1].get("geometry_group_id") or "")
            for plane, tile_id in selected.items()
        }
        if any(
            str(entries[tile_id][1].get("geometry_group_id") or "") != corrected_groups[SAGITTAL_PLANE_GROUP_ROLE[plane]]
            for plane, tile_id in selected.items()
        ) or corrected_groups["central"] != group_for_role["central"]:
            raise AnatomyCardError("anatomy_map_sagittal_side_ambiguous", "Side correction would change central group membership.")
        if sagittal:
            previous_groups = {
                SAGITTAL_PLANE_GROUP_ROLE[plane]: str(entries[tile_id][1].get("geometry_group_id") or "")
                for plane, tile_id in sagittal["sagittal_t2"].items()
            }
            if corrected_groups != previous_groups:
                raise AnatomyCardError("anatomy_map_sequence_pair_conflict", "T1/T2 physical side groups disagree.")
        sagittal[role] = selected
        canonicalization[role] = {
            "policy": "dicom_lps_x_side_authority_v3",
            "model_role_order_differs_from_physical_order": selected_ids != ordered_ids,
            "proposed_tile_ids": proposed_by_plane,
            "physical_patient_right_to_left_tile_ids": ordered_ids,
            "patient_lps_x_mm": {
                plane: round(_plane_coordinate(entries[tile_id][1]), 4)
                for plane, tile_id in selected.items()
            },
        }

    for assignment in group_assignments:
        assignment["anatomical_role"] = next(
            role for role, group_id in corrected_groups.items() if group_id == assignment["group_id"]
        )
    for plane in SAGITTAL_PLANES:
        t2 = _plane_coordinate(entries[sagittal["sagittal_t2"][plane]][1])
        t1 = _plane_coordinate(entries[sagittal["sagittal_t1"][plane]][1])
        if abs(t2 - t1) > 8.0:
            raise AnatomyCardError(
                "anatomy_map_sequence_pair_conflict",
                f"The T1/T2 {plane} pair is separated by more than 8 mm.",
            )

    groups = _axial_groups(package)
    raw_levels = structured.get("axial_levels")
    if not groups:
        raise AnatomyCardError(
            "anatomy_map_axial_groups_missing",
            "The workstation did not establish neutral axial geometry groups.",
        )
    if not isinstance(raw_levels, list) or len(raw_levels) != len(groups):
        raise AnatomyCardError(
            "anatomy_map_level_count_conflict",
            "The anatomy map must bind every neutral axial group exactly once.",
        )
    canonicalization["axial_levels"] = {}
    levels = []
    seen_groups: set[str] = set()
    seen_levels: set[str] = set()
    axial_series_id = sequence_assignments["axial_t2"]["series_id"]
    for raw in raw_levels:
        if not isinstance(raw, dict):
            raise AnatomyCardError(
                "anatomy_map_level_invalid", "An axial group mapping is not an object."
            )
        group_id = str(raw.get("axial_group_id") or "")
        level = str(raw.get("level") or "")
        if group_id not in groups or group_id in seen_groups:
            raise AnatomyCardError(
                "anatomy_map_group_identity_conflict",
                "An axial group identity is unknown or repeated.",
            )
        if level not in ANATOMICAL_LEVEL_ORDER or level in seen_levels:
            raise AnatomyCardError(
                "anatomy_map_level_identity_conflict",
                "An anatomical level is unknown or assigned to multiple axial groups.",
            )
        bounds = raw.get("axial_frames")
        try:
            first, last = int(bounds[0]), int(bounds[1])
        except (IndexError, TypeError, ValueError) as exc:
            raise AnatomyCardError(
                "anatomy_map_level_range_invalid", f"{group_id} has no valid frame range."
            ) from exc
        if first <= 0 or last < first:
            raise AnatomyCardError(
                "anatomy_map_level_range_invalid", f"{group_id} has an invalid frame range."
            )
        if (first, last) != groups[group_id]:
            raise AnatomyCardError(
                "anatomy_map_slab_conflict",
                f"{group_id} does not match its measured axial group boundary.",
            )
        proposed = raw.get("axial_planes")
        if not isinstance(proposed, dict):
            raise AnatomyCardError(
                "anatomy_map_axial_planes_missing", f"{group_id} has no axial plane map."
            )
        proposed_planes: dict[str, str] = {}
        for plane in AXIAL_PLANES:
            tile_id = str(proposed.get(plane) or "")
            entry = entries.get(tile_id)
            if entry is None or _tile_series_id(entries, tile_id) != axial_series_id:
                raise AnatomyCardError(
                    "anatomy_map_role_conflict",
                    f"{group_id} {plane} does not reference the series assigned to axial_t2.",
                )
            frame = int(entry[1].get("capture_frame") or 0)
            tile_group = str(entry[1].get("geometry_group_id") or "")
            if not first <= frame <= last:
                raise AnatomyCardError(
                    "anatomy_map_axial_level_conflict",
                    f"{group_id} {plane} falls outside its measured geometry group.",
                )
            if tile_group and tile_group != group_id:
                raise AnatomyCardError(
                    "anatomy_map_axial_group_conflict",
                    f"{group_id} {plane} references a tile owned by another group.",
                )
            proposed_planes[plane] = tile_id
        if len(set(proposed_planes.values())) != len(AXIAL_PLANES):
            raise AnatomyCardError(
                "anatomy_map_duplicate_axial_plane",
                f"{group_id} reuses an axial source plane.",
            )
        axial_coordinates = {
            tile_id: _axial_superior_coordinate(entries[tile_id][1])
            for tile_id in proposed_planes.values()
        }
        if len({round(value, 4) for value in axial_coordinates.values()}) != len(AXIAL_PLANES):
            raise AnatomyCardError(
                "anatomy_map_duplicate_axial_position",
                f"{group_id} has repeated axial patient-space positions.",
            )
        physical_order = sorted(
            proposed_planes.values(),
            key=axial_coordinates.__getitem__,
            reverse=True,
        )
        canonicalization["axial_levels"][group_id] = {
            "policy": "dicom_lps_z_record_only_no_semantic_relabel_v1",
            "assigned_level": level,
            "proposed_tile_ids": proposed_planes,
            "physical_superior_to_inferior_tile_ids": physical_order,
            "lps_z_mm_by_tile_id": {
                tile_id: round(value, 4) for tile_id, value in axial_coordinates.items()
            },
        }
        seen_groups.add(group_id)
        seen_levels.add(level)
        levels.append({
            "axial_group_id": group_id,
            "level": level,
            "axial_frames": [first, last],
            "axial_planes": proposed_planes,
        })
    levels.sort(key=lambda row: ANATOMICAL_LEVEL_ORDER.index(row["level"]))
    lumbar_levels = [row for row in levels if row["level"] in STANDARD_LEVELS]
    context_levels = [row for row in levels if row["level"] in CONTEXT_LEVELS]
    if not lumbar_levels:
        raise AnatomyCardError(
            "anatomy_map_lumbar_coverage_missing",
            "No axial group was mapped within the lumbar diagnostic scope.",
        )
    for row in context_levels:
        _, members = _axial_group_entries(
            entries, {"sequence_assignments": sequence_assignments}, row,
        )
        row["analysis_scope"] = "context_only"
        row["source_tiles"] = [dict(entry[1]) for entry in members]
    coverage = {
        "policy": "preserve_extra_anatomy_without_lumbar_relabeling_v1",
        "mapped_group_count": len(levels),
        "lumbar_group_count": len(lumbar_levels),
        "context_group_count": len(context_levels),
        "not_assessed_levels": [row["level"] for row in context_levels],
        "context_axial_frames": [row["axial_frames"] for row in context_levels],
    }
    group_integrity = {
        "version": "1.0.0",
        "status": "validated",
        "groups": [
            {
                "group_id": group_id,
                "series_role": sequence_role,
                "member_kind": "source_slice",
                "original_members": list(
                    sagittal_groups[group_id]["series_members"][
                        sequence_assignments[sequence_role]["series_id"]
                    ]["source_slices"]
                ),
                "anatomical_role": next(
                    row["anatomical_role"]
                    for row in group_assignments if row["group_id"] == group_id
                ),
            }
            for group_id in sagittal_groups
            for sequence_role in ("sagittal_t2", "sagittal_t1")
        ] + [
            {
                "group_id": row["axial_group_id"],
                "series_role": "axial_t2",
                "member_kind": "capture_frame",
                "original_members": list(
                    range(row["axial_frames"][0], row["axial_frames"][1] + 1)
                ),
                "mapped_level": row["level"],
            }
            for row in levels
        ],
    }
    return {
        "schema_version": ANATOMY_CARD_SCHEMA_VERSION,
        "sequence_assignments": sequence_assignments,
        "sagittal_group_assignments": group_assignments,
        "sagittal_order_policy": "dicom_lps_x_side_authority_v3",
        "axial_order_policy": "dicom_lps_z_record_only_no_semantic_relabel_v1",
        "geometry_canonicalization": canonicalization,
        "sagittal_planes": sagittal,
        "axial_levels": lumbar_levels,
        "context_axial_levels": context_levels,
        "coverage": coverage,
        "group_integrity": group_integrity,
    }


def _page_image(package: AnalysisPackage, page: dict) -> Image.Image:
    index = int(page.get("image_index") or 0)
    match = next((image for image in package.images if image.index == index), None)
    if match is None:
        raise AnatomyCardError(
            "anatomy_atlas_page_missing", "An anatomy tile references a missing atlas page."
        )
    try:
        return Image.open(match.path).convert("RGB")
    except (OSError, ValueError) as exc:
        raise AnatomyCardError(
            "anatomy_atlas_page_unreadable", "An anatomy atlas page cannot be decoded."
        ) from exc


def _extract_tile(
    package: AnalysisPackage, entry: tuple[dict, dict, int], cache: dict[int, Image.Image]
) -> Image.Image:
    page, _tile, position = entry
    image_index = int(page.get("image_index") or 0)
    image = cache.get(image_index)
    if image is None:
        image = cache[image_index] = _page_image(package, page)
    try:
        width, height = map(int, page["tile_size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AnatomyCardError(
            "anatomy_atlas_layout_missing", "An atlas page has no usable tile size."
        ) from exc
    stored_box = _tile.get("page_box")
    if isinstance(stored_box, (list, tuple)) and len(stored_box) == 4:
        try:
            box = tuple(int(value) for value in stored_box)
        except (TypeError, ValueError) as exc:
            raise AnatomyCardError(
                "anatomy_atlas_layout_conflict",
                "An atlas tile has an invalid stored page box.",
            ) from exc
    else:
        role = str(page.get("role") or "")
        default_columns = 6 if role.startswith("sagittal_") else 5
        columns = int(page.get("page_columns") or min(default_columns, len(page.get("tiles", ()))) or 1)
        header = int(page.get("page_header") or 42)
        cell_label = int(page.get("cell_label") or 28)
        left = (position % columns) * width
        top = header + (position // columns) * (height + cell_label)
        box = (left, top, left + width, top + height)
    if box[2] > image.width or box[3] > image.height:
        raise AnatomyCardError(
            "anatomy_atlas_layout_conflict", "An atlas tile lies outside its stored page."
        )
    return image.crop(box)


def _fit_tile(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    copy = image.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    tile = Image.new("RGB", size, "black")
    tile.paste(copy, ((size[0] - copy.width) // 2, (size[1] - copy.height) // 2))
    return tile


def _paste_labeled(
    canvas: Image.Image,
    image: Image.Image,
    origin: tuple[int, int],
    size: tuple[int, int],
    label: str,
    color: str,
) -> None:
    draw = ImageDraw.Draw(canvas)
    x, y = origin
    draw.text((x + 4, y), label, fill="white", font=ImageFont.load_default())
    top = y + 20
    canvas.paste(_fit_tile(image, size), (x, top))
    draw.rectangle((x, top, x + size[0] - 1, top + size[1] - 1), outline=color, width=2)


def _card_spec(request_key: str) -> dict[str, Any]:
    try:
        template = get_card_template(
            "mri", "lumbar_spine", "screening", request_key
        )
    except LookupError as exc:
        raise AnatomyCardError(
            "anatomy_card_request_unknown", f"Unknown anatomy card {request_key}."
        ) from exc
    sagittal_roles = tuple(
        role for role in template.required_sequences if role.startswith("sagittal_")
    )
    return {
        "template_id": template.template_id,
        "anatomical_targets": template.anatomical_targets,
        "sagittal": [
            (role, plane)
            for role in sagittal_roles
            for plane in template.sagittal_positions
        ],
        "sagittal_size": template.sagittal_tile_size,
        "sagittal_columns": template.sagittal_columns,
        "axial": bool(template.axial_positions),
        "axial_size": template.axial_tile_size or (0, 0),
        "layout_strategy": template.layout_strategy,
    }


def _sagittal_group_entries(
    package: AnalysisPackage,
    entries: Dict[str, tuple[dict, dict, int]],
    anatomy_map: dict[str, Any],
    sequence_role: str,
    anatomical_role: str,
) -> tuple[str, list[tuple[dict, dict, int]]]:
    group_id = next(
        (
            str(row.get("group_id") or "")
            for row in anatomy_map["sagittal_group_assignments"]
            if row.get("anatomical_role") == anatomical_role
        ),
        "",
    )
    series_id = str(
        anatomy_map["sequence_assignments"][sequence_role].get("series_id") or ""
    )
    geometry = package.evidence_audit.get("geometry_groups") or {}
    group = next(
        (
            row for row in geometry.get("sagittal", ())
            if isinstance(row, dict) and row.get("group_id") == group_id
        ),
        None,
    )
    members = group.get("series_members", {}).get(series_id) if group else None
    source_slices = members.get("source_slices") if isinstance(members, dict) else None
    if not group_id or not isinstance(source_slices, list) or not source_slices:
        raise AnatomyCardError(
            "anatomy_card_sagittal_group_missing",
            f"No immutable {sequence_role} {anatomical_role} group is available.",
        )
    by_slice = {
        int(entry[1].get("source_slice") or 0): entry
        for entry in entries.values()
        if str(entry[1].get("series_id") or "") == series_id
    }
    selected = [by_slice.get(int(source_slice)) for source_slice in source_slices]
    if any(entry is None for entry in selected):
        raise AnatomyCardError(
            "anatomy_card_sagittal_group_incomplete",
            f"The {sequence_role} {anatomical_role} geometry group is incomplete.",
        )
    return group_id, [entry for entry in selected if entry is not None]


def _axial_group_entries(
    entries: Dict[str, tuple[dict, dict, int]],
    anatomy_map: dict[str, Any],
    level: dict[str, Any],
) -> tuple[str, list[tuple[dict, dict, int]]]:
    """Return every source tile in one immutable axial geometry group."""
    group_id = str(level.get("axial_group_id") or "")
    first, last = map(int, level.get("axial_frames") or (0, -1))
    series_id = str(
        anatomy_map["sequence_assignments"]["axial_t2"].get("series_id") or ""
    )
    selected = sorted(
        (
            entry for entry in entries.values()
            if str(entry[1].get("series_id") or "") == series_id
            and str(entry[1].get("geometry_group_id") or "") == group_id
            and first <= int(entry[1].get("capture_frame") or 0) <= last
        ),
        key=lambda entry: int(entry[1].get("capture_frame") or 0),
    )
    current = [int(entry[1].get("capture_frame") or 0) for entry in selected]
    expected = list(range(first, last + 1))
    if not group_id or current != expected:
        raise AnatomyCardError(
            "geometry_group_integrity_error",
            f"{group_id or 'unknown axial group'} changed from {expected} to {current}.",
        )
    return group_id, selected


def _screening_card_group_integrity(
    anatomy_map: dict[str, Any], used: list[dict[str, Any]],
) -> dict[str, Any]:
    """Prove that every group shown to screening is a complete parent group."""
    contracts = anatomy_map.get("group_integrity") or {}
    rows = contracts.get("groups") if isinstance(contracts, dict) else None
    if not isinstance(rows, list):
        raise AnatomyCardError(
            "geometry_group_integrity_error",
            "The anatomy map has no immutable group-membership contract.",
        )
    verified = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        group_id = str(raw.get("group_id") or "")
        role = str(raw.get("series_role") or "")
        kind = str(raw.get("member_kind") or "")
        original = [int(value) for value in raw.get("original_members") or ()]
        matching = [
            item for item in used
            if str(item.get("geometry_group_id") or item.get("axial_group_id") or "")
            == group_id
            and str(item.get("role") or "") == role
        ]
        if not matching:
            continue
        key = "capture_frame" if kind == "capture_frame" else "source_slice"
        current = list(dict.fromkeys(int(item.get(key) or 0) for item in matching))
        if current != original:
            raise AnatomyCardError(
                "geometry_group_integrity_error",
                f"{group_id} {role} changed from {original} to {current} before screening.",
            )
        verified.append({
            "group_id": group_id,
            "series_role": role,
            "member_kind": kind,
            "original_members": original,
            "current_members": current,
            "selection_kind": "complete_group",
            "status": "intact",
        })
    if not verified:
        raise AnatomyCardError(
            "geometry_group_integrity_error",
            "The screening card contains no auditable geometry group.",
        )
    return {"version": "1.0.0", "status": "validated", "groups": verified}


def _render_card(
    package: AnalysisPackage,
    anatomy_map: dict[str, Any],
    request_key: str,
    destination: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entries = _atlas_entries(package)
    spec = _card_spec(request_key)
    myelographic_images: list[tuple[Image.Image, dict[str, Any]]] = []
    myelographic_warnings: list[str] = []
    myelographic_provenance: list[dict[str, Any]] = []
    if request_key == "canal_neural":
        from .canal_evidence import discover_context_sources, render_context
        sources = discover_context_sources(package.source_series, package.study_instance_uid)
        myelographic_images, myelographic_warnings = render_context(
            sources, package.study_instance_uid,
            local_provenance=myelographic_provenance,
        )
        _atomic_json(destination.with_name("canal_context_sources.local.json"), {
            "schema_version": "1.0.0", "source_series": sources,
            "selected_images": myelographic_provenance,
        })

    sagittal_blocks: list[dict[str, Any]] = []
    if request_key in {"disc", "canal_neural"}:
        group_id, group_entries = _sagittal_group_entries(
            package, entries, anatomy_map, "sagittal_t2", "central"
        )
        items = [
            {"role": "sagittal_t2", "plane": "central", "entry": entry}
            for entry in group_entries
        ]
        sagittal_blocks.append({
            "section_kind": "sagittal_geometry_group",
            "sequence_role": "sagittal_t2",
            "anatomical_role": "central",
            "geometry_group_id": group_id,
            "label": f"SAGITTAL T2 | CENTRAL REGION | {group_id}",
            "items": items,
            "columns": min(4, len(items)),
        })
    elif request_key == "foraminal":
        for sequence_role in ("sagittal_t2", "sagittal_t1"):
            for anatomical_role in ("right_lateral", "left_lateral"):
                group_id, group_entries = _sagittal_group_entries(
                    package, entries, anatomy_map, sequence_role, anatomical_role
                )
                sagittal_blocks.append({
                    "section_kind": "sagittal_geometry_group",
                    "sequence_role": sequence_role,
                    "anatomical_role": anatomical_role,
                    "geometry_group_id": group_id,
                    "label": (
                        f"{sequence_role.upper()} | {anatomical_role.replace('_', ' ').upper()} "
                        f"FORAMINAL REGION | {group_id}"
                    ),
                    "items": [
                        {"role": sequence_role, "plane": anatomical_role, "entry": entry}
                        for entry in group_entries
                    ],
                    "columns": 3,
                })
    elif request_key == "posterior_elements":
        for sequence_role in ("sagittal_t2", "sagittal_t1"):
            for anatomical_role in ("right_lateral", "central", "left_lateral"):
                group_id, group_entries = _sagittal_group_entries(
                    package, entries, anatomy_map, sequence_role, anatomical_role
                )
                items = [
                    {"role": sequence_role, "plane": anatomical_role, "entry": entry}
                    for entry in group_entries
                ]
                sagittal_blocks.append({
                    "section_kind": "sagittal_geometry_group",
                    "sequence_role": sequence_role,
                    "anatomical_role": anatomical_role,
                    "geometry_group_id": group_id,
                    "label": (
                        f"{sequence_role.upper()} | {anatomical_role.replace('_', ' ').upper()} "
                        f"POSTERIOR REGION | {group_id}"
                    ),
                    "items": items,
                    "columns": min(4, len(items)),
                })
    else:
        central_group_id = next(
            (
                str(row.get("group_id") or "")
                for row in anatomy_map["sagittal_group_assignments"]
                if row.get("anatomical_role") == "central"
            ),
            "",
        )
        _t2_group, t2_entries = _sagittal_group_entries(
            package, entries, anatomy_map, "sagittal_t2", "central"
        )
        _t1_group, t1_entries = _sagittal_group_entries(
            package, entries, anatomy_map, "sagittal_t1", "central"
        )
        items = []
        for t2_entry, t1_entry in zip_longest(t2_entries, t1_entries):
            if t2_entry is not None:
                items.append({
                    "role": "sagittal_t2", "plane": "central", "entry": t2_entry,
                })
            if t1_entry is not None:
                items.append({
                    "role": "sagittal_t1", "plane": "central", "entry": t1_entry,
                })
        sagittal_blocks.append({
            "section_kind": "sagittal_grid",
            "sequence_role": "matched_sagittal_t2_t1",
            "anatomical_role": "central",
            "geometry_group_id": central_group_id,
            "label": "MATCHED SAGITTAL T2 / T1 GRID | EXISTING ENDPLATE LAYOUT",
            "items": items,
            "columns": 2,
        })

    axial_blocks = []
    if spec["axial"]:
        for level in anatomy_map["axial_levels"]:
            group_id, group_entries = _axial_group_entries(entries, anatomy_map, level)
            axial_blocks.append({
                "section_kind": "axial_geometry_group",
                "sequence_role": "axial_t2",
                "anatomical_role": "level_bound_axial_group",
                "geometry_group_id": group_id,
                "anatomical_level": level["level"],
                "label": (
                    f"{level['level']} | {level['axial_group_id']} | AX FRAMES "
                    f"{level['axial_frames'][0]}-{level['axial_frames'][1]}"
                ),
                "items": [
                    {
                        "role": "axial_t2",
                        "plane": "group_member",
                        "entry": entry,
                    }
                    for entry in group_entries
                ],
                "columns": min(4, len(group_entries)),
            })

    sag_width, sag_height = spec["sagittal_size"]
    axial_width, axial_height = spec["axial_size"]

    def block_height(block: dict[str, Any], size: tuple[int, int]) -> int:
        rows = int(math.ceil(len(block["items"]) / max(1, int(block["columns"]))))
        return CARD_BLOCK_HEADER + rows * (size[1] + 26)

    sagittal_height = sum(
        block_height(block, (sag_width, sag_height)) for block in sagittal_blocks
    ) + CARD_GROUP_GAP * max(0, len(sagittal_blocks) - 1)
    axial_height_total = sum(
        block_height(block, (axial_width, axial_height)) for block in axial_blocks
    ) + CARD_GROUP_GAP * max(0, len(axial_blocks) - 1)
    content_width = max(
        max((block["columns"] * sag_width for block in sagittal_blocks), default=1),
        max((block["columns"] * axial_width for block in axial_blocks), default=1),
    )
    content_height = (
        CARD_HEADER_HEIGHT
        + sagittal_height
        + (CARD_SECTION_GAP if axial_blocks and sagittal_blocks else 0)
        + axial_height_total
        + (CARD_SECTION_GAP + 386 if myelographic_images else 0)
    )
    canvas = Image.new("RGB", (content_width, content_height), "black")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text(
        (8, 10),
        f"ANATOMY GATE CARD | {request_key.upper()} | NORMALITY NOT ASSESSED",
        fill="white",
        font=font,
    )
    draw.text(
        (8, 30),
        "Whitespace and section headers define groups; labels are secondary and color is tertiary.",
        fill="#cbd5e1",
        font=font,
    )
    cache: dict[int, Image.Image] = {}
    used: list[dict[str, Any]] = []
    layout_blocks: list[dict[str, Any]] = []

    def render_blocks(
        blocks: list[dict[str, Any]],
        size: tuple[int, int],
        start_top: int,
    ) -> int:
        cursor = start_top
        width, height = size
        for block_index, block in enumerate(blocks):
            draw.text((8, cursor + 6), block["label"], fill="white", font=font)
            tile_top = cursor + CARD_BLOCK_HEADER
            columns = max(1, int(block["columns"]))
            color = _GEOMETRY_GROUP_COLORS.get(
                block.get("anatomical_role"), "#a855f7"
            )
            tile_ids = []
            for index, item in enumerate(block["items"]):
                column = index % columns
                row = index // columns
                origin = (column * width, tile_top + row * (height + 26))
                entry = item["entry"]
                tile_id = str(entry[1].get("tile_id") or "")
                _paste_labeled(
                    canvas,
                    _extract_tile(package, entry, cache),
                    origin,
                    (width, height),
                    f"{item['role'].upper()} | {item['plane'].replace('_', ' ').upper()} | {tile_id}",
                    color,
                )
                record = dict(entry[1])
                record["role"] = item["role"]
                record["semantic_role"] = item["role"]
                record["display_role"] = f"{item['role']}.{item['plane']}"
                record["geometry_group_id"] = block["geometry_group_id"]
                record["card_box"] = [
                    origin[0], origin[1] + 20,
                    origin[0] + width, origin[1] + 20 + height,
                ]
                if block["section_kind"] == "axial_geometry_group":
                    record["anatomical_level"] = block["anatomical_level"]
                    record["axial_group_id"] = block["geometry_group_id"]
                used.append(record)
                tile_ids.append(tile_id)
            bottom = cursor + block_height(block, size)
            layout_blocks.append({
                "section_kind": block["section_kind"],
                "sequence_role": block["sequence_role"],
                "anatomical_role": block["anatomical_role"],
                "geometry_group_id": block["geometry_group_id"],
                "anatomical_level": block.get("anatomical_level"),
                "display_label": block["label"],
                "box": [0, cursor, canvas.width, bottom],
                "tile_ids": tile_ids,
            })
            cursor = bottom + (CARD_GROUP_GAP if block_index < len(blocks) - 1 else 0)
        return cursor

    content_top = CARD_HEADER_HEIGHT
    myelographic_records = []
    if myelographic_images:
        draw.text(
            (8, content_top + 6),
            "MR MYELOGRAPHY | CANAL-CALIBER OVERVIEW ONLY | NOT A LEVEL LOCALIZER",
            fill="white", font=font,
        )
        tile_top = content_top + CARD_BLOCK_HEADER
        for index, (image, record) in enumerate(myelographic_images):
            origin = (index * 420, tile_top)
            size = (400, 360)
            canvas.paste(_fit_tile(image, size), origin)
            draw.rectangle(
                (origin[0], origin[1], origin[0] + size[0] - 1, origin[1] + size[1] - 1),
                outline="#f59e0b", width=2,
            )
            draw.text((origin[0] + 4, origin[1] + 4), record["tile_id"], fill="white", font=font)
            myelographic_records.append(dict(record, card_box=[
                origin[0], origin[1], origin[0] + size[0], origin[1] + size[1],
            ]))
        content_top += 386 + CARD_SECTION_GAP

    cursor = render_blocks(sagittal_blocks, (sag_width, sag_height), content_top)
    if axial_blocks:
        cursor += CARD_SECTION_GAP
        cursor = render_blocks(axial_blocks, (axial_width, axial_height), cursor)

    _atomic_image(canvas, destination)
    metadata = {
        "schema_version": ANATOMY_CARD_SCHEMA_VERSION,
        "template_id": spec["template_id"],
        "card_family": "screening",
        "request_key": request_key,
        "anatomical_targets": list(spec["anatomical_targets"]),
        "normality_assessed": False,
        "anatomy_map": anatomy_map,
        "layout_contract": {
            "version": "1.0.0",
            "strategy": spec["layout_strategy"],
            "primary_grouping_signal": "physical_spacing",
            "secondary_grouping_signal": "section_headers",
            "tertiary_grouping_signal": "color",
            "minimum_group_gap_px": CARD_GROUP_GAP,
            "blocks": layout_blocks,
        },
        "geometry_group_ids": {
            "sagittal": sorted({
                str(item.get("geometry_group_id") or "")
                for item in used
                if str(item.get("role") or "").startswith("sagittal_")
                and item.get("geometry_group_id")
            }),
            "axial": sorted({
                str(item.get("axial_group_id") or "")
                for item in used
                if item.get("axial_group_id")
            }),
        },
        "group_integrity": _screening_card_group_integrity(anatomy_map, used),
        **({"myelographic_context": {
            "status": "included" if myelographic_records else "unavailable",
            "role": "overview_only",
            "localization_allowed": False,
            "images": myelographic_records,
            "warnings": myelographic_warnings,
        }} if request_key == "canal_neural" else {}),
        "tile_count": len(used),
        "image_file": destination.name,
    }
    return used, metadata


def prepare_anatomy_cards(
    package: AnalysisPackage, structured: Any,
) -> AnalysisPackage:
    """Validate Gate 1 and return five immutable Gate 1-to-2 card images."""
    anatomy_map = normalize_anatomy_map(package, structured)
    output_dir = package.session_dir / ".evidence" / ANATOMY_CARD_MODE
    request_keys = tuple(
        template.key
        for template in list_card_templates(
            modality="mri", body_part="lumbar_spine", family="screening"
        )
    )
    images = []
    pages = []
    card_records = []
    for image_index, request_key in enumerate(request_keys, start=1):
        image_path = output_dir / f"anatomy_{image_index:02d}_{request_key}.png"
        tiles, metadata = _render_card(package, anatomy_map, request_key, image_path)
        sidecar_name = f"anatomy_{image_index:02d}_{request_key}.card.json"
        _atomic_json(output_dir / sidecar_name, metadata)
        public_tiles = [dict(tile, image_index=image_index) for tile in tiles]
        pages.append({
            "image_index": image_index,
            "role": "anatomy_card",
            "request_key": request_key,
            "tiles": public_tiles,
        })
        card_record = {
            "image_index": image_index,
            "template_id": metadata["template_id"],
            "request_key": request_key,
            "image_file": image_path.name,
            "card_json_file": sidecar_name,
            "tile_count": len(public_tiles),
        }
        card_records.append(card_record)
        images.append(PackagedImage(
            image_path,
            (
                f"Anatomy-only Gate 1 card for {request_key}; normality and pathology "
                "were not assessed while this card was assembled."
            ),
            f"anatomy-card-{request_key}",
            image_index,
            evidence_mode=ANATOMY_CARD_MODE,
            card_payload={"anatomy_card": metadata},
        ))
    audit = {
        "schema_version": ANATOMY_CARD_SCHEMA_VERSION,
        "evidence_mode": ANATOMY_CARD_MODE,
        "coordinate_space": package.evidence_audit.get(
            "coordinate_space", "tile_content_0_1000"
        ),
        "anatomy_map": anatomy_map,
        "measured_slabs": package.evidence_audit.get("measured_slabs", []),
        "cards": card_records,
        "pages": pages,
        "source_atlas": {
            "schema_version": package.evidence_audit.get("schema_version"),
            "series_contract": package.evidence_audit.get("series_contract", {}),
            "geometry_groups": package.evidence_audit.get("geometry_groups", {}),
            "screening_sampling": package.evidence_audit.get("screening_sampling", {}),
            "budget": package.evidence_audit.get("budget", {}),
            "capacity_notes": package.evidence_audit.get("capacity_notes", []),
        },
        "warnings": [
            "Outside lumbar diagnostic scope: "
            + ", ".join(anatomy_map["coverage"]["not_assessed_levels"])
            + ". Source images and anatomy mapping retained; pathology was not assessed."
        ] if anatomy_map["context_axial_levels"] else [],
    }
    _atomic_json(output_dir / ANATOMY_CARD_MANIFEST, audit)
    return AnalysisPackage(
        package.session_dir,
        package.session_id,
        package.protocol_id,
        package.analysis,
        package.header,
        images,
        study_instance_uid=package.study_instance_uid,
        source_series=package.source_series,
        evidence_audit=audit,
    )


def screening_package_for(
    package: AnalysisPackage, request_key: str,
) -> AnalysisPackage:
    """Return one renumbered anatomy card for one pathology-screening request."""
    match = next(
        (
            image for image in package.images
            if (image.card_payload.get("anatomy_card") or {}).get("request_key") == request_key
        ),
        None,
    )
    if match is None:
        raise AnatomyCardError(
            "anatomy_card_missing", f"No anatomy card exists for {request_key}."
        )
    card_metadata = match.card_payload.get("anatomy_card") or {}
    integrity = card_metadata.get("group_integrity")
    groups = integrity.get("groups") if isinstance(integrity, dict) else None
    if (
        not isinstance(integrity, dict)
        or integrity.get("status") != "validated"
        or not isinstance(groups, list)
        or not groups
        or any(
            not isinstance(row, dict)
            or row.get("status") != "intact"
            or row.get("original_members") != row.get("current_members")
            for row in groups
        )
    ):
        raise AnatomyCardError(
            "geometry_group_integrity_error",
            f"The {request_key} screening card changed an immutable geometry group.",
        )
    original_index = match.index
    page = next(
        (
            item for item in package.evidence_audit.get("pages", ())
            if isinstance(item, dict) and item.get("image_index") == original_index
        ),
        None,
    )
    if page is None:
        raise AnatomyCardError(
            "anatomy_card_inventory_missing", f"No tile inventory exists for {request_key}."
        )
    local_page = dict(page)
    local_page["image_index"] = 1
    local_page["tiles"] = [
        dict(tile, image_index=1)
        for tile in page.get("tiles", ()) if isinstance(tile, dict)
    ]
    anatomy_map = package.evidence_audit.get("anatomy_map") or {}
    header = (
        "ANATOMY GATE\n"
        + "  This request contains exactly one anatomy-only card created after a separate "
        + "mapping gate. Do not relabel its levels or acquisition-plane roles.\n"
        + "  Physical whitespace and section rows define geometry groups; labels are "
        + "secondary and color is tertiary. Never merge separate blocks.\n"
        + "  Every displayed screening block is one complete immutable geometry group. "
        + "Do not move, split, merge, or relabel any individual member.\n"
        + "  context_axial_levels are outside the lumbar diagnostic scope. Their "
        + "images remain in the source atlas; do not diagnose them, mark them normal, "
        + "or assign them to another level. Screen only axial_levels.\n"
        + "ANATOMY_MAP_JSON\n"
        + json.dumps(anatomy_map, ensure_ascii=False, separators=(",", ":"))
    )
    audit = dict(package.evidence_audit)
    audit["pages"] = [local_page]
    audit["cards"] = [
        item for item in package.evidence_audit.get("cards", ())
        if isinstance(item, dict) and item.get("request_key") == request_key
    ]
    audit["anatomy_card_request"] = request_key
    return AnalysisPackage(
        package.session_dir,
        package.session_id,
        package.protocol_id,
        package.analysis,
        header,
        [PackagedImage(
            match.path,
            match.caption,
            match.session,
            1,
            capture=match.capture,
            source_path=match.source_path,
            evidence_mode=match.evidence_mode,
            card_payload=match.card_payload,
        )],
        study_instance_uid=package.study_instance_uid,
        source_series=package.source_series,
        evidence_audit=audit,
    )
