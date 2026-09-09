"""Bounded, diagnosis-free attention handoff; no image IO or network.

Boxes refer either to validated source-atlas tile content or original capture
pixels (normalized 0..1000), never to a later crop/composite. Cross-plane
associations are model proposals until local DICOM geometry validates them.
Raw responses remain in the stage audit; only this allowlist reaches diagnosis.
"""

from __future__ import annotations

import math

SCHEMA_VERSION = "2.9.0"
LEVEL_CARD_TEMPLATE_VERSION = "1.6.0"
LEVEL_CARD_SLOT_ROLES = {
    "sagittal_t2.right_foraminal_plane": "sagittal_t2",
    "sagittal_t2.right_paracentral_plane": "sagittal_t2",
    "sagittal_t2.midline_plane": "sagittal_t2",
    "sagittal_t2.left_paracentral_plane": "sagittal_t2",
    "sagittal_t2.left_foraminal_plane": "sagittal_t2",
    "sagittal_t1.right_foraminal_plane": "sagittal_t1",
    "sagittal_t1.right_paracentral_plane": "sagittal_t1",
    "sagittal_t1.midline_plane": "sagittal_t1",
    "sagittal_t1.left_paracentral_plane": "sagittal_t1",
    "sagittal_t1.left_foraminal_plane": "sagittal_t1",
    "axial_t2.disc_level_plane": "axial_t2",
    "axial_t2.max_abnormality_plane": "axial_t2",
    "axial_t2.caudal_extent_plane": "axial_t2",
}
STRUCTURES = frozenset({
    "disc", "endplate", "bone_marrow", "vertebral_body", "posterior_element",
    "facet_joint", "ligamentum_flavum", "central_canal", "lateral_recess",
    "neural_foramen", "nerve_root", "conus", "cauda_equina", "epidural_space",
    "paraspinal_soft_tissue", "alignment", "other",
})
LEVEL_ORDER = ("T12-L1", "L1-L2", "L2-L3", "L3-L4", "L4-L5", "L5-S1")
LEVELS = frozenset(LEVEL_ORDER)
VERTEBRAE = frozenset({"T12", "L1", "L2", "L3", "L4", "L5", "S1"})
ENDPLATE_SURFACES = frozenset({"superior", "inferior", "both", "not_applicable"})
PANES = {"sagittal_t2": "sagittal", "sagittal_t1": "sagittal", "axial_t2": "axial"}
_VERTEBRAL_STRUCTURES = frozenset({"endplate", "bone_marrow", "vertebral_body"})
_CONFIDENCE_ORDER = {"low": 0, "moderate": 1, "high": 2}
_SALIENCE_ORDER = {"unspecified": 0, "subtle": 1, "definite": 2, "marked": 3}
_PRIORITY_ORDER = {
    "unspecified": 0, "minor": 1, "secondary": 2, "major": 3, "dominant": 4,
}
_PERSISTENCE_ORDER = {
    "unspecified": 0,
    "single_slice": 1,
    "two_adjacent_slices": 2,
    "three_or_more_adjacent_slices": 3,
}
_FEATURE_ORDERS = {
    "signal_change": {
        "not_assessable": -1, "none": 0, "subtle": 1, "definite": 2, "marked": 3,
    },
    "contour_change": {
        "not_assessable": -1, "none": 0, "subtle": 1, "definite": 2, "marked": 3,
    },
    "space_effacement": {
        "not_assessable": -1, "none": 0, "subtle": 1, "definite": 2, "marked": 3,
    },
    "visible_neural_relationship": {
        "not_assessable": -1, "none": 0, "contact": 1,
        "displacement": 2, "compression": 3,
    },
}


def _choice(value, choices, default):
    return value if isinstance(value, str) and value in choices else default


def _observable_features(value):
    """Keep only bounded observations; never transport a diagnostic label."""
    source = value if isinstance(value, dict) else {}
    return {
        name: source[name]
        for name, order in _FEATURE_ORDERS.items()
        if isinstance(source.get(name), str) and source[name] in order
    }


def _strongest(values, order, default="unspecified"):
    return max(values, key=lambda value: order.get(value, -1), default=default)


def _legacy_structure(value):
    """Recover anatomy from old saved candidates without forwarding a label."""
    label = str(value or "").lower()[:160]
    for structure, tokens in (
        ("ligamentum_flavum", ("flavum",)), ("facet_joint", ("facet", "synovial")),
        ("nerve_root", ("root",)), ("lateral_recess", ("recess",)),
        ("neural_foramen", ("foramin",)), ("central_canal", ("canal",)),
        ("endplate", ("endplate", "modic", "schmorl")), ("bone_marrow", ("marrow",)),
        ("disc", ("disc", "bulg", "protrus", "extrus", "herniat", "annular", "desiccat")),
        ("vertebral_body", ("vertebr", "osteophyte",)),
        ("alignment", ("listhesis", "scoliosis", "alignment")),
        ("conus", ("conus",)), ("cauda_equina", ("cauda",)),
        ("epidural_space", ("epidural",)),
    ):
        if any(token in label for token in tokens):
            return structure
    return "other"


def _inventory(package):
    result = {}
    for image in getattr(package, "images", ()):
        session = image.session.lower()
        panes = image.capture.get("panes", {})
        for pane, expected_session in PANES.items():
            if expected_session != session:
                continue
            metadata = panes.get(pane, {})
            if metadata.get("role") not in {"primary", "synced"}:
                continue
            key = (session, image.index, pane)
            # Ambiguous identities are unusable, not last-write-wins.
            result[key] = image if key not in result else None
    return result


def _box(value):
    if not isinstance(value, list) or len(value) != 4:
        return None
    if not all(type(v) in (int, float) and 0 <= v <= 1000 and math.isfinite(v) for v in value):
        return None
    ymin, xmin, ymax, xmax = value
    return list(value) if ymin < ymax and xmin < xmax else None


def _correlated_inventory(package):
    if getattr(package, "evidence_audit", {}).get("coordinate_space") != "tile_content_0_1000":
        return None
    from .screening_evidence import tile_inventory

    return tile_inventory(package)


def _card_geometry_expectations(package):
    audit = getattr(package, "evidence_audit", {})
    audit = audit if isinstance(audit, dict) else {}
    anatomy_map = audit.get("anatomy_map")
    anatomy_map = anatomy_map if isinstance(anatomy_map, dict) else {}
    group_for_role = {
        str(row.get("anatomical_role") or ""): str(row.get("group_id") or "")
        for row in anatomy_map.get("sagittal_group_assignments", ())
        if isinstance(row, dict)
    }
    plane_role = {
        "right_foraminal_plane": "right_lateral",
        "right_paracentral_plane": "central",
        "midline_plane": "central",
        "left_paracentral_plane": "central",
        "left_foraminal_plane": "left_lateral",
    }
    sagittal = {}
    for slot in LEVEL_CARD_SLOT_ROLES:
        role, _, plane = slot.partition(".")
        if role.startswith("sagittal_") and plane in plane_role:
            sagittal[slot] = group_for_role.get(plane_role[plane], "")
    axial = {
        str(row.get("level") or ""): str(row.get("axial_group_id") or "")
        for row in anatomy_map.get("axial_levels", ())
        if isinstance(row, dict)
    }
    contracts = anatomy_map.get("group_integrity") or {}
    members = {
        (str(row.get("group_id") or ""), str(row.get("series_role") or "")):
        [int(value) for value in row.get("original_members") or ()]
        for row in contracts.get("groups", ())
        if isinstance(row, dict)
    } if isinstance(contracts, dict) else {}
    if not members:
        contract_rows = {}
        for page in audit.get("pages", ()):
            if not isinstance(page, dict):
                continue
            for tile in page.get("tiles", ()):
                if not isinstance(tile, dict):
                    continue
                group_id = str(tile.get("geometry_group_id") or "")
                role = str(tile.get("source_role") or tile.get("role") or "")
                member = (
                    tile.get("capture_frame")
                    if role == "axial_t2" else tile.get("source_slice")
                )
                if not group_id or type(member) is not int or member < 1:
                    continue
                key = (group_id, role)
                record = contract_rows.setdefault(key, {
                    "group_id": group_id,
                    "series_role": role,
                    "member_kind": (
                        "capture_frame" if role == "axial_t2" else "source_slice"
                    ),
                    "original_members": [],
                })
                if member not in record["original_members"]:
                    record["original_members"].append(member)
        for record in contract_rows.values():
            record["original_members"].sort()
        members = {
            key: list(record["original_members"])
            for key, record in contract_rows.items()
        }
        if contract_rows:
            contracts = {
                "version": "1.0.0",
                "status": "validated",
                "groups": list(contract_rows.values()),
            }
    return {
        "sagittal": sagittal,
        "axial_by_level": axial,
        "members": members,
        "group_integrity": contracts if isinstance(contracts, dict) else {},
    }


def _normalize_level_card_templates(
    structured, inventory, abnormal_levels, attention_tiles_by_level, warnings,
    *, require_complete=False, geometry_expectations=None
):
    """Retain only source-atlas identities that match a predefined card slot."""
    proposed = structured.get("level_card_templates")
    proposed = proposed if isinstance(proposed, list) else []
    by_level = {}
    for raw in proposed[:8]:
        if not isinstance(raw, dict):
            warnings.append("screening_card_template_invalid")
            continue
        level = _choice(raw.get("level"), LEVELS, None)
        if level is None or level not in abnormal_levels:
            warnings.append("screening_card_template_unbound_level")
            continue
        if level in by_level:
            warnings.append("screening_card_template_duplicate_level")
            continue
        by_level[level] = raw

    templates = []
    for level in sorted(abnormal_levels, key=LEVEL_ORDER.index):
        raw = by_level.get(level)
        raw_slots = raw.get("slots") if isinstance(raw, dict) else None
        raw_slots = raw_slots if isinstance(raw_slots, dict) else {}
        slots = []
        sagittal_patient_x = {}
        sagittal_source_slices = {}
        axial_frames = []
        for slot, expected_role in LEVEL_CARD_SLOT_ROLES.items():
            selection = raw_slots.get(slot)
            if selection is None:
                continue
            if not isinstance(selection, dict):
                warnings.append("screening_card_slot_invalid")
                continue
            image_index = selection.get("image")
            tile_id = selection.get("tile_id")
            if type(image_index) is not int or not isinstance(tile_id, str):
                warnings.append("screening_card_slot_invalid")
                continue
            tile = inventory.get((image_index, tile_id)) if inventory is not None else None
            if tile is None:
                warnings.append("screening_card_slot_not_in_inventory")
                continue
            if tile.get("role") != expected_role:
                warnings.append("screening_card_slot_role_mismatch")
                continue
            source_slice = tile.get("source_slice")
            capture_frame = tile.get("capture_frame")
            if type(source_slice) is not int or source_slice < 1:
                warnings.append("screening_card_slot_source_invalid")
                continue
            if expected_role == "axial_t2" and (
                type(capture_frame) is not int or capture_frame < 1
            ):
                warnings.append("screening_card_slot_source_invalid")
                continue
            geometry_group_id = str(tile.get("geometry_group_id") or "")
            expected_group_id = (
                (geometry_expectations or {}).get("axial_by_level", {}).get(level, "")
                if expected_role == "axial_t2"
                else (geometry_expectations or {}).get("sagittal", {}).get(slot, "")
            )
            if expected_group_id and geometry_group_id != expected_group_id:
                warnings.append("screening_card_slot_geometry_group_mismatch")
                continue
            parent_members = list(
                (geometry_expectations or {}).get("members", {}).get(
                    (geometry_group_id, expected_role), ()
                )
            )
            selected_member = (
                capture_frame if expected_role == "axial_t2" else source_slice
            )
            if parent_members and selected_member not in parent_members:
                warnings.append("screening_card_slot_parent_membership_mismatch")
                continue
            raw_score = selection.get("abnormality_conspicuity")
            score = raw_score if type(raw_score) is int and 0 <= raw_score <= 3 else None
            if raw_score is not None and score is None:
                warnings.append("screening_card_slot_conspicuity_invalid")
            raw_attention_ids = selection.get("attention_ids")
            raw_attention_ids = raw_attention_ids if isinstance(raw_attention_ids, list) else []
            tile_attention = attention_tiles_by_level.get(level, {})
            matched_attention_ids = {
                attention_id
                for attention_id, identities in tile_attention.items()
                if (image_index, tile_id) in identities
            }
            attention_ids = []
            for attention_id in raw_attention_ids[:8]:
                if (
                    not isinstance(attention_id, str)
                    or attention_id not in matched_attention_ids
                ):
                    warnings.append("screening_card_slot_attention_unbound")
                    continue
                if attention_id not in attention_ids:
                    attention_ids.append(attention_id)
            attention_ids = list(dict.fromkeys([
                *attention_ids,
                *sorted(matched_attention_ids),
            ]))[:8]
            record = {
                "slot": slot,
                "role": expected_role,
                "source_slice": source_slice,
                "capture_frame": capture_frame if type(capture_frame) is int else None,
                "selection": "gemini_atlas_proposal",
                "abnormality_conspicuity": score,
                "attention_ids": attention_ids,
                "geometry_group_id": geometry_group_id or None,
                "parent_group_id": geometry_group_id or None,
                "parent_group_members": parent_members,
            }
            slots.append(record)
            if expected_role == "axial_t2":
                axial_frames.append(capture_frame)
            if expected_role.startswith("sagittal_"):
                sagittal_source_slices[slot] = source_slice
                mapping = tile.get("mapping")
                if isinstance(mapping, dict) and mapping.get("kind") == "volume":
                    direction = mapping.get("direction")
                    spacing = mapping.get("spacing")
                    slice_index = mapping.get("slice_index")
                    if (
                        isinstance(direction, list) and len(direction) == 9
                        and isinstance(spacing, list) and len(spacing) == 3
                        and type(slice_index) is int
                        and abs(float(direction[2])) >= 0.5
                    ):
                        sagittal_patient_x[slot] = (
                            float(direction[2]) * float(spacing[2]) * slice_index
                        )
        for role in ("sagittal_t2", "sagittal_t1"):
            names = [
                f"{role}.right_foraminal_plane",
                f"{role}.right_paracentral_plane",
                f"{role}.midline_plane",
                f"{role}.left_paracentral_plane",
                f"{role}.left_foraminal_plane",
            ]
            if all(name in sagittal_patient_x for name in names):
                coordinates = [sagittal_patient_x[name] for name in names]
                if not all(
                    left + 0.1 < right
                    for left, right in zip(coordinates, coordinates[1:])
                ):
                    slots = [item for item in slots if item["role"] != role]
                    warnings.append("screening_card_slot_sagittal_order_mismatch")
                    continue
            if all(name in sagittal_source_slices for name in names):
                source_indices = [sagittal_source_slices[name] for name in names]
                steps = [
                    abs(right - left)
                    for left, right in zip(source_indices, source_indices[1:])
                ]
                if not (
                    1 <= steps[0] <= 3
                    and 2 <= steps[1] <= 3
                    and 2 <= steps[2] <= 3
                    and 1 <= steps[3] <= 3
                ):
                    slots = [item for item in slots if item["role"] != role]
                    warnings.append("screening_card_slot_sagittal_spacing_mismatch")
        if len(axial_frames) == 3 and len(set(axial_frames)) != 3:
            slots = [item for item in slots if item["role"] != "axial_t2"]
            warnings.append("screening_card_slot_axial_duplicate")
        status = (
            "complete" if len(slots) == len(LEVEL_CARD_SLOT_ROLES)
            else "partial" if slots else "unavailable"
        )
        if raw is None and require_complete:
            warnings.append("screening_level_card_template_missing")
        elif raw is not None and status != "complete":
            warnings.append("screening_level_card_template_incomplete")
        templates.append({
            "level": level,
            "status": status,
            "slots": slots,
            "group_integrity": {
                "status": "validated" if slots and all(
                    item.get("parent_group_id") == item.get("geometry_group_id")
                    and item.get("parent_group_members")
                    for item in slots
                ) else "legacy_unavailable",
            },
        })
    return templates


def _geometry_summary(points):
    """Classify deterministic links without turning geometry into diagnosis."""
    if not points:
        return None, {"status": "unavailable", "roles": [], "max_separation_mm": None}
    coordinates = [item["patient_lps"] for item in points]
    # A medoid is robust to one loose model box and remains an observed point.
    distances = []
    for first in coordinates:
        distances.append(sum(math.dist(first, second) for second in coordinates))
    anchor = coordinates[min(range(len(coordinates)), key=distances.__getitem__)]
    max_separation = max(math.dist(anchor, point) for point in coordinates)
    roles = list(dict.fromkeys(item["role"] for item in points))
    groups = {item["frame_group"] for item in points}
    plane_families = {PANES.get(role, "unknown") for role in roles}
    if len(groups) != 1 or any(group.startswith("unverified-") for group in groups):
        status = "frame_of_reference_unverified"
    elif len(plane_families) >= 2 and max_separation <= 25.0:
        status = "verified_multiplanar"
    elif len(plane_families) >= 2:
        status = "cross_plane_conflict"
    elif len(roles) >= 2 and max_separation <= 25.0:
        status = "verified_multiseries_same_plane"
    elif max_separation <= 25.0:
        status = "verified_single_plane"
    else:
        status = "same_plane_conflict"
    return anchor, {
        "status": status,
        "roles": roles,
        "max_separation_mm": round(float(max_separation), 2),
    }


def _anatomical_key(focus, unique_ordinal=None):
    """Return the narrowest diagnosis-free identity that is safe to merge."""
    structure = focus["structure"]
    level = focus["level"]
    vertebra = focus["vertebra"]
    if structure == "endplate" and vertebra:
        surface = focus.get("endplate_surface") or "unresolved"
        site = f"vertebra:{vertebra}:endplate:{surface}"
    elif structure in _VERTEBRAL_STRUCTURES and vertebra:
        site = f"vertebra:{vertebra}"
    elif level != "unclear":
        site = f"level:{level}"
    elif vertebra:
        site = f"vertebra:{vertebra}"
    else:
        # Two unlocalized abnormalities are not demonstrably the same lesion.
        site = f"unresolved:{unique_ordinal}"
    return structure, site


def _resolved_laterality(values):
    definite = {value for value in values if value not in {"indeterminate", "not_applicable"}}
    if not definite:
        return "not_applicable" if values and set(values) == {"not_applicable"} else "indeterminate"
    if definite == {"left", "right"} or "bilateral" in definite:
        return "bilateral"
    if len(definite) == 1:
        return next(iter(definite))
    # For example central plus right can describe a continuous paracentral focus,
    # but screening cannot safely encode that in one categorical side field.
    return "indeterminate"


def _downgrade_confidence(value):
    return {"high": "moderate", "moderate": "low", "low": "low"}[value]


def _merge_geometry(focuses, warnings):
    geometries = [item.get("geometry") for item in focuses if isinstance(item.get("geometry"), dict)]
    if not geometries:
        return None, None
    roles = list(dict.fromkeys(
        role for geometry in geometries for role in geometry.get("roles", ()) if role in PANES
    ))
    anchors = [tuple(item["geometry_anchor_lps"]) for item in focuses
               if isinstance(item.get("geometry_anchor_lps"), list)
               and len(item["geometry_anchor_lps"]) == 3]
    statuses = {str(item.get("status") or "") for item in geometries}
    separations = [float(item["max_separation_mm"]) for item in geometries
                   if type(item.get("max_separation_mm")) in (int, float)]
    anchor = None
    anchor_separation = 0.0
    if anchors:
        distances = [sum(math.dist(first, second) for second in anchors) for first in anchors]
        anchor = anchors[min(range(len(anchors)), key=distances.__getitem__)]
        anchor_separation = max(math.dist(anchor, item) for item in anchors)
    max_separation = max([anchor_separation, *separations], default=0.0)
    planes = {PANES.get(role, "unknown") for role in roles}
    if not roles and not anchors and statuses <= {"", "unavailable"}:
        status = "unavailable"
        anchor = None
    elif any(status.endswith("conflict") for status in statuses) or anchor_separation > 25.0:
        status = "cross_plane_conflict" if len(planes) >= 2 else "same_plane_conflict"
        anchor = None
        warnings.append("screening_correspondence_geometry_conflict")
    elif "frame_of_reference_unverified" in statuses:
        status = "frame_of_reference_unverified"
        anchor = None
        warnings.append("screening_correspondence_geometry_unverified")
    elif len(planes) >= 2:
        status = "verified_multiplanar"
    elif len(roles) >= 2:
        status = "verified_multiseries_same_plane"
    else:
        status = "verified_single_plane"
    geometry = {
        "status": status,
        "roles": roles,
        "max_separation_mm": round(max_separation, 2),
    }
    return geometry, ([round(value, 4) for value in anchor] if anchor is not None else None)


def _spatial_clusters(focuses):
    """Keep same-anatomy observations separate when LPS proves they are distant."""
    anchored = []
    unanchored = []
    for focus in focuses:
        value = focus.get("geometry_anchor_lps")
        if isinstance(value, list) and len(value) == 3:
            anchored.append((focus, tuple(float(item) for item in value)))
        else:
            unanchored.append(focus)
    if not anchored:
        return [list(focuses)]
    clusters = []
    for focus, anchor in anchored:
        for cluster in clusters:
            if any(math.dist(anchor, existing) <= 25.0 for existing in cluster["anchors"]):
                cluster["focuses"].append(focus)
                cluster["anchors"].append(anchor)
                break
        else:
            clusters.append({"focuses": [focus], "anchors": [anchor]})
    if len(clusters) == 1:
        clusters[0]["focuses"].extend(unanchored)
    else:
        # An unlocalized observation cannot safely choose between spatially
        # distinct lesions that share the same anatomical label.
        clusters.extend({"focuses": [focus], "anchors": []} for focus in unanchored)
    return [cluster["focuses"] for cluster in clusters]


def _canonicalize(result, normal_keys):
    """Collapse repeated observations into one contradiction-free handoff row."""
    warnings = result["warnings"]
    grouped = {}
    for ordinal, focus in enumerate(result["findings"], 1):
        grouped.setdefault(_anatomical_key(focus, ordinal), []).append(focus)

    canonical_groups = []
    for key, focuses in grouped.items():
        clusters = _spatial_clusters(focuses)
        if len(clusters) > 1:
            warnings.append("screening_spatially_distinct_focus_split")
        canonical_groups.extend((key, cluster) for cluster in clusters)

    canonical = []
    for key, focuses in canonical_groups:
        merged = dict(focuses[0])
        merged["locations"] = []
        merged["key_frames"] = {"axial": [], "sagittal": []}
        location_ids = set()
        for focus in focuses:
            for location in focus["locations"]:
                identity = repr(sorted(location.items()))
                if identity not in location_ids:
                    location_ids.add(identity)
                    merged["locations"].append(location)
            for session in ("axial", "sagittal"):
                for frame in focus["key_frames"][session]:
                    if frame not in merged["key_frames"][session]:
                        merged["key_frames"][session].append(frame)
        merged["laterality"] = _resolved_laterality([item["laterality"] for item in focuses])
        merged["confidence"] = max(
            (item["confidence"] for item in focuses), key=_CONFIDENCE_ORDER.__getitem__
        )
        merged["visual_salience"] = _strongest(
            (item["visual_salience"] for item in focuses), _SALIENCE_ORDER,
        )
        merged["within_study_priority"] = _strongest(
            (item["within_study_priority"] for item in focuses), _PRIORITY_ORDER,
        )
        merged["slice_persistence"] = _strongest(
            (item["slice_persistence"] for item in focuses), _PERSISTENCE_ORDER,
        )
        merged["observable_features"] = {}
        for name, order in _FEATURE_ORDERS.items():
            values = [
                item.get("observable_features", {}).get(name)
                for item in focuses
                if item.get("observable_features", {}).get(name) in order
            ]
            if values:
                merged["observable_features"][name] = _strongest(values, order, values[0])
        if key in normal_keys:
            merged["confidence"] = _downgrade_confidence(merged["confidence"])
            warnings.append("screening_assessment_conflict_resolved_abnormal")
        geometry, anchor = _merge_geometry(focuses, warnings)
        if geometry is not None:
            merged["geometry"] = geometry
        else:
            merged.pop("geometry", None)
        if anchor is not None:
            merged["geometry_anchor_lps"] = anchor
        else:
            merged.pop("geometry_anchor_lps", None)
        canonical.append(merged)

    abnormal_keys = set(grouped)
    unavailable = []
    unavailable_keys = set()
    for ordinal, focus in enumerate(result["not_assessable"], 1):
        key = _anatomical_key(focus, f"na-{ordinal}")
        if key in abnormal_keys:
            warnings.append("screening_assessment_conflict_resolved_abnormal")
            continue
        if key in normal_keys:
            warnings.append("screening_assessment_conflict_resolved_not_assessable")
        if key in unavailable_keys:
            continue
        unavailable_keys.add(key)
        unavailable.append(focus)

    for ordinal, focus in enumerate([*canonical, *unavailable], 1):
        focus["attention_id"] = f"attention-{ordinal:02d}"
    result["findings"] = canonical
    result["not_assessable"] = unavailable
    result["warnings"] = list(dict.fromkeys(warnings))
    if result["warnings"]:
        result["status"] = "degraded"
    return result


def normalize_attention(structured, package=None):
    """Return only neutral anatomy and source-bound locations, never raw prose.

    Without a capture package no coordinates or frame IDs can be validated.
    A rejected location does not erase a possibly abnormal anatomical focus.
    """
    result = {
        "schema_version": SCHEMA_VERSION, "status": "available",
        "correspondence_status": "model_proposed_not_geometry_verified",
        "coordinate_space": "original_capture_full_image_0_1000_ymin_xmin_ymax_xmax",
        "findings": [], "not_assessable": [], "normal_count": 0, "warnings": [],
        "group_integrity": {},
    }
    warnings = result["warnings"]
    if not isinstance(structured, dict) or not isinstance(structured.get("findings"), list):
        result["status"] = "unavailable"
        warnings.append("screening_attention_unavailable")
        return result
    inventory = _inventory(package)
    correlated_inventory = _correlated_inventory(package)
    geometry_expectations = _card_geometry_expectations(package)
    source_integrity = geometry_expectations.get("group_integrity") or {}
    proposed_integrity = structured.get("group_integrity") or {}
    if source_integrity and proposed_integrity and source_integrity != proposed_integrity:
        warnings.append("screening_group_integrity_contract_conflict")
    result["group_integrity"] = dict(source_integrity or proposed_integrity)
    normal_keys = set()
    if correlated_inventory is not None:
        result["correspondence_status"] = "deterministic_patient_geometry_validation"
        result["coordinate_space"] = "tile_content_0_1000_ymin_xmin_ymax_xmax"
    rows = structured["findings"]
    contract_version = structured.get("schema_version")
    current_contract = contract_version in {
        SCHEMA_VERSION, "2.8.0", "3.0.0", "3.1.0", "3.2.0", "3.3.0", "3.4.0",
    }
    priority_contract = contract_version in {
        "2.3.0", SCHEMA_VERSION, "2.8.0", "3.0.0", "3.1.0", "3.2.0", "3.3.0", "3.4.0",
    }
    if len(rows) > 64:
        warnings.append("screening_attention_limit_applied")
    for ordinal, row in enumerate(rows[:64], 1):
        if not isinstance(row, dict):
            warnings.append("screening_attention_invalid_row")
            continue
        legacy = "assessment" not in row and isinstance(row.get("candidate"), str)
        assessment = row.get("assessment", "abnormal" if legacy else None)
        if assessment not in ("abnormal", "not_assessable"):
            if assessment == "normal":
                structure = _choice(row.get("structure"), STRUCTURES, "other")
                normal_focus = {
                    "structure": structure,
                    "level": _choice(row.get("level"), LEVELS, "unclear"),
                    "vertebra": _choice(row.get("vertebra"), VERTEBRAE, None),
                    "endplate_surface": _choice(
                        row.get("endplate_surface"), ENDPLATE_SURFACES,
                        "not_applicable",
                    ),
                }
                normal_keys.add(_anatomical_key(normal_focus, f"normal-{ordinal}"))
                result["normal_count"] += 1
                continue
            warnings.append("screening_attention_invalid_assessment")
            continue
        if priority_contract and assessment == "abnormal" and (
            row.get("visual_salience") not in _SALIENCE_ORDER
            or row.get("visual_salience") == "unspecified"
            or row.get("within_study_priority") not in _PRIORITY_ORDER
            or row.get("within_study_priority") == "unspecified"
            or row.get("slice_persistence") not in _PERSISTENCE_ORDER
            or row.get("slice_persistence") == "unspecified"
        ):
            warnings.append("screening_priority_contract_incomplete")
        structure = _choice(row.get("structure"), STRUCTURES, None)
        if structure is None:
            structure = _legacy_structure(row.get("candidate")) if legacy else "other"
            if not legacy:
                warnings.append("screening_attention_unknown_structure")
        if legacy:
            warnings.append("screening_attention_legacy_anatomy_adapter")
        focus = {
            "attention_id": f"attention-{ordinal:02d}",
            "structure": structure, "assessment": assessment,
            "level": _choice(row.get("level"), LEVELS, "unclear"),
            "vertebra": _choice(row.get("vertebra"), VERTEBRAE, None),
            "endplate_surface": _choice(
                row.get("endplate_surface"), ENDPLATE_SURFACES,
                "not_applicable",
            ),
            "laterality": _choice(row.get("laterality"),
                                  {"left", "right", "central", "bilateral", "indeterminate",
                                   "not_applicable"},
                                  "indeterminate"),
            "confidence": _choice(row.get("confidence"), {"low", "moderate", "high"}, "low"),
            "visual_salience": _choice(
                row.get("visual_salience"), _SALIENCE_ORDER, "unspecified",
            ),
            "within_study_priority": _choice(
                row.get("within_study_priority"), _PRIORITY_ORDER, "unspecified",
            ),
            "slice_persistence": _choice(
                row.get("slice_persistence"), _PERSISTENCE_ORDER, "unspecified",
            ),
            "observable_features": _observable_features(row.get("observable_features")),
            "locations": [], "key_frames": {"axial": [], "sagittal": []},
        }
        locations = row.get("locations", [])
        locations = list(locations) if isinstance(locations, list) else []
        if legacy and not locations:
            key_frames = row.get("key_frames", {})
            key_frames = key_frames if isinstance(key_frames, dict) else {}
            for session, pane in (("axial", "axial_t2"), ("sagittal", "sagittal_t2")):
                frames = key_frames.get(session, [])
                if isinstance(frames, list):
                    locations.extend({"session": session, "frame": frame, "pane": pane}
                                     for frame in frames[:5])
        if len(locations) > 15:
            warnings.append("screening_location_limit_applied")
        seen = set()
        geometry_points = []
        for location in locations[:15]:
            if not isinstance(location, dict):
                warnings.append("screening_location_invalid")
                continue
            if correlated_inventory is not None:
                image_index = location.get("image")
                tile_id = location.get("tile_id")
                if type(image_index) is not int or not isinstance(tile_id, str):
                    warnings.append("screening_location_invalid")
                    continue
                tile = correlated_inventory.get((image_index, tile_id))
                if tile is None:
                    warnings.append("screening_tile_not_in_inventory")
                    continue
                box = _box(location.get("box_2d"))
                if box is None:
                    warnings.append("screening_box_invalid")
                    continue
                try:
                    from .screening_evidence import tile_box_center_lps

                    patient_lps = tile_box_center_lps(tile, box)
                except (KeyError, TypeError, ValueError):
                    warnings.append("screening_tile_geometry_invalid")
                    continue
                identity = (image_index, tile_id, tuple(box))
                if identity in seen:
                    continue
                seen.add(identity)
                role = tile["role"]
                frame = tile.get("capture_frame")
                focus["locations"].append({
                    "image": image_index,
                    "tile_id": tile_id,
                    "pane": role,
                    "source_slice": tile.get("source_slice"),
                    "capture_frame": frame,
                    "box_2d": box,
                })
                geometry_points.append({
                    "patient_lps": patient_lps,
                    "role": role,
                    "frame_group": str(tile.get("frame_group") or ""),
                })
                session_key = PANES.get(role)
                if session_key and type(frame) is int and frame not in focus["key_frames"][session_key]:
                    focus["key_frames"][session_key].append(frame)
                continue

            session, frame, pane = (location.get(key) for key in ("session", "frame", "pane"))
            if (not isinstance(session, str) or not isinstance(pane, str)
                    or type(frame) is not int or frame < 1):
                warnings.append("screening_location_invalid")
                continue
            key = (session.lower(), frame, pane)
            image = inventory.get(key)
            if image is None:
                warnings.append("screening_location_not_in_capture_inventory")
                continue
            box = _box(location.get("box_2d"))
            if location.get("box_2d") is not None and box is None:
                warnings.append("screening_box_invalid")
            if box is not None and image.evidence_mode != "layout":
                # V1 repacks panes. No inverse box transform is defined here.
                box = None
                warnings.append("screening_box_nonlayout_transform_unavailable")
            identity = (*key, tuple(box or ()))
            if identity in seen:
                continue
            seen.add(identity)
            focus["locations"].append({
                "session": key[0], "frame": frame, "pane": pane, "box_2d": box,
                "source_file": image.as_dict(package.session_dir)["file"],
            })
            if frame not in focus["key_frames"][key[0]]:
                focus["key_frames"][key[0]].append(frame)
        if correlated_inventory is not None:
            anchor, geometry = _geometry_summary(geometry_points)
            focus["geometry"] = geometry
            if anchor is not None and geometry["status"].startswith("verified_"):
                focus["geometry_anchor_lps"] = [round(value, 4) for value in anchor]
            if geometry["status"].endswith("conflict"):
                warnings.append("screening_correspondence_geometry_conflict")
            elif geometry["status"] == "frame_of_reference_unverified":
                warnings.append("screening_correspondence_geometry_unverified")
        if assessment == "abnormal" and not focus["locations"]:
            warnings.append("screening_focus_without_valid_location")
        target = "not_assessable" if assessment == "not_assessable" else "findings"
        result[target].append(focus)
    result = _canonicalize(result, normal_keys)
    if contract_version in {"3.2.0", "3.3.0", "3.4.0"}:
        for focus in (*result["findings"], *result["not_assessable"]):
            focus.pop("observable_features", None)
    abnormal_levels = {
        focus["level"]
        for focus in result["findings"]
        if focus.get("level") in LEVELS
    }
    attention_tiles_by_level = {}
    for focus in result["findings"]:
        level = focus.get("level")
        attention_id = focus.get("attention_id")
        if level in LEVELS and isinstance(attention_id, str):
            identities = {
                (location.get("image"), location.get("tile_id"))
                for location in focus.get("locations", ())
                if isinstance(location, dict)
                and type(location.get("image")) is int
                and isinstance(location.get("tile_id"), str)
            }
            attention_tiles_by_level.setdefault(level, {})[attention_id] = identities
    result["level_card_template_version"] = LEVEL_CARD_TEMPLATE_VERSION
    result["level_card_templates"] = _normalize_level_card_templates(
        structured,
        correlated_inventory,
        abnormal_levels,
        attention_tiles_by_level,
        result["warnings"],
        require_complete=(
            current_contract and not structured.get("atomic_pipeline_version")
        ),
        geometry_expectations=geometry_expectations,
    )
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    if result["warnings"]:
        result["status"] = "degraded"
    return result


def attention_context(attention):
    """Serialize a previously normalized object at the orchestrator boundary."""
    import json

    # Exact patient coordinates remain local orchestration data. The diagnostic
    # reader receives verified tile/frame relationships, never raw LPS values.
    public_attention = {
        "schema_version": attention.get("schema_version", SCHEMA_VERSION),
        "correspondence_status": attention.get("correspondence_status", "unavailable"),
        "coordinate_space": attention.get("coordinate_space", "unavailable"),
        "findings": json.loads(json.dumps(attention.get("findings", []))),
        "not_assessable": json.loads(json.dumps(attention.get("not_assessable", []))),
    }
    material_prefixes = (
        "screening_assessment_conflict_",
        "screening_correspondence_",
        "screening_focus_without_valid_location",
        "screening_location_limit_applied",
        "screening_attention_limit_applied",
        "screening_priority_",
        "screening_tile_not_in_inventory",
        "screening_card_",
        "screening_level_card_",
    )
    material_issues = [
        warning for warning in attention.get("warnings", [])
        if isinstance(warning, str) and warning.startswith(material_prefixes)
    ]
    handoff_status = (
        "unavailable" if attention.get("status") == "unavailable"
        else "degraded" if material_issues else "available"
    )
    public_attention["status"] = handoff_status
    public_attention["handoff_quality"] = {
        "status": handoff_status,
        "issues": material_issues,
    }
    for collection in ("findings", "not_assessable"):
        for focus in public_attention.get(collection, []):
            focus.pop("geometry_anchor_lps", None)
    correlated = attention.get("correspondence_status") == "deterministic_patient_geometry_validation"
    correspondence_text = (
        "Locations identify source screening-atlas tiles, not image numbers in the "
        "diagnostic package. Tile identities and cross-plane links were checked against "
        "deterministic patient-space DICOM geometry, and focused sheets were built from "
        "the retained anchor. Geometry verifies correspondence, not anatomy, level, side, "
        "normality or diagnosis. Independently re-derive those clinical fields. "
        if correlated
        else
        "Locations reference original capture images, not focused composites. Frame "
        "membership and box bounds are checked; anatomy, side, level and cross-plane "
        "correspondence are NOT thereby verified. "
    )
    return (
        "SCREENING ATTENTION MAP - LOCALIZATION ONLY.\n"
        "This is a canonical handoff with one canonical row per anatomical focus; "
        "duplicate observations and contradictory screening assessments were resolved "
        "locally before this request. These are HYPOTHESES about abnormal presence, "
        "not diagnoses. Independently "
        "decide normal/artifact versus pathology, then classify every retained focus. "
        "Confidence describes detection, never diagnostic certainty. Visual salience and "
        "within-study priority describe evidence routing only and must not be copied into "
        "diagnostic severity or clinical urgency.\n"
        + correspondence_text + "Do not apply these coordinates to "
        "a resized/cropped sheet. Use its provenance and the images to correlate.\n"
        "An unavailable/degraded map or not_assessable structure is not a negative exam. "
        "Keep the broad overview safety sweep and clinical-context checks.\n\n"
        + json.dumps(public_attention, ensure_ascii=True, indent=2) + "\n"
    )
