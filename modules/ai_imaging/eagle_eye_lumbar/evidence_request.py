"""Bound untrusted model attention hints into a deterministic evidence plan."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from itertools import islice
from typing import Any, Dict, Iterable, Optional

from .screening_attention import LEVEL_CARD_SLOT_ROLES, STRUCTURES


SCHEMA_VERSION = "1.7.0"
ADDITIONAL_FINDINGS_LEVEL = "additional_findings"
ALLOWED_LEVELS = (
    "T12-L1",
    "L1-L2",
    "L2-L3",
    "L3-L4",
    "L4-L5",
    "L5-S1",
)
_LEVEL_RANK = {level: index for index, level in enumerate(ALLOWED_LEVELS)}
_LEVEL_PATTERN = re.compile(
    r"\b(T12\s*[-–—/]\s*L1|L[1-4]\s*[-–—/]\s*L[2-5]|L5\s*[-–—/]\s*S1)\b",
    re.IGNORECASE,
)
_LEVEL_MAP_LINE = re.compile(
    r"^\s*(T12\s*[-–—/]\s*L1|L[1-4]\s*[-–—/]\s*L[2-5]|L5\s*[-–—/]\s*S1)"
    r"\s*:\s*axial\s+frames?\s+(\d+)\s*(?:[-–—]\s*(\d+))?",
    re.IGNORECASE | re.MULTILINE,
)

# Report auditing is broader than the deliberately restricted attention planner.
REPORT_LEVELS = tuple(f"T{i}-T{i + 1}" for i in range(1, 12)) + ALLOWED_LEVELS
_AUDIT_MAX_CHARACTERS = 200_000
_AUDIT_MAX_ROWS = 64
_AUDIT_MAP_CANDIDATE = re.compile(
    r"^\s*[TL]\d{1,2}\s*[-–—/]\s*[TLS]\d{1,2}\s*:\s*axial\s+frames?\b", re.I | re.M,
)
_AUDIT_MAP_LINE = re.compile(
    r"^\s*([TL]\d{1,2}\s*[-–—/]\s*[TLS]\d{1,2})\s*:\s*axial\s+frames?\s+"
    r"(\d{1,6})\s*(?:[-–—]\s*(\d{1,6}))?\s*(?:$|[;(])", re.I | re.M,
)


def level_map_rows(text: str) -> list[dict]:
    """Keep raw explicit assignments, including duplicates and invalid ranges."""
    return [{"level": re.sub(r"\s*[-–—/]\s*", "-", m[1].upper()),
             "frames": [int(m[2]), int(m[3] or m[2])]}
            for m in islice(_AUDIT_MAP_LINE.finditer(str(text or "")[:_AUDIT_MAX_CHARACTERS]),
                            _AUDIT_MAX_ROWS)]


def audit_level_maps(screening_text: str, verification_text: str,
                     measured_slabs=()) -> dict:
    """Compare labels on stable capture ranges; neither model is ground truth.

    This detects assignment conflicts, not vertebrae. Capture geometry can
    establish slab boundaries, but cannot alone establish anatomical numbering.
    """
    texts = {"screening": str(screening_text or ""),
             "verification": str(verification_text or "")}
    inputs = {source: level_map_rows(text) for source, text in texts.items()}
    measured = {tuple(map(int, bounds)) for bounds in measured_slabs}
    issues = []
    mappings = {}
    for source, rows in inputs.items():
        candidate_count = sum(1 for _ in _AUDIT_MAP_CANDIDATE.finditer(
            texts[source][:_AUDIT_MAX_CHARACTERS]))
        if len(texts[source]) > _AUDIT_MAX_CHARACTERS or candidate_count > _AUDIT_MAX_ROWS:
            issues.append(f"{source}_input_limit_exceeded")
        if candidate_count != len(rows):
            issues.append(f"{source}_unparsed_assignment")
        mapping = {}
        levels = set()
        if not rows:
            issues.append(f"{source}_level_map_missing")
        previous_end = 0
        previous_rank = -1
        for row in sorted(rows, key=lambda item: item["frames"]):
            bounds = tuple(row["frames"])
            level = row["level"]
            rank = REPORT_LEVELS.index(level) if level in REPORT_LEVELS else -1
            if bounds[0] < 1 or bounds[1] < bounds[0] or rank < 0:
                issues.append(f"{source}_invalid_assignment")
            if level in levels or bounds in mapping:
                issues.append(f"{source}_duplicate_assignment")
            if bounds[0] <= previous_end:
                issues.append(f"{source}_overlapping_ranges")
            if bounds[0] != previous_end + 1:
                issues.append(f"{source}_incomplete_frame_coverage")
            if rank <= previous_rank:
                issues.append(f"{source}_nonmonotonic_levels")
            previous_end, previous_rank = bounds[1], rank
            levels.add(level)
            mapping[bounds] = level
        if measured and set(mapping) != measured:
            issues.append(f"{source}_measured_slab_mismatch")
        mappings[source] = mapping
    first, last = mappings["screening"], mappings["verification"]
    if set(first) != set(last):
        issues.append("stage_frame_ranges_disagree")
    if any(first[b] != last[b] for b in first.keys() & last.keys()):
        issues.append("level_assignment_conflict")
    offsets = [REPORT_LEVELS.index(last[b]) - REPORT_LEVELS.index(first[b])
               for b in first.keys() & last.keys()
               if first[b] in REPORT_LEVELS and last[b] in REPORT_LEVELS]
    uniform_offset = None
    if (len(offsets) >= 2 and len(offsets) == len(first) == len(last)
            and set(first) == set(last) and len(set(offsets)) == 1):
        uniform_offset = offsets[0]
    return {
        "schema_version": "1.0.0",
        "status": "unavailable" if not first or not last else "conflict" if issues else "consistent",
        "anatomical_numbering_verified": False,
        "uniform_level_offset": uniform_offset,
        "issues": list(dict.fromkeys(issues)),
        "measured_slab_count": len(measured),
        "slabs": [{"slab_id": f"axial:{b[0]}-{b[1]}", "frames": list(b),
                   "screening_level": first.get(b), "verification_level": last.get(b)}
                  for b in sorted(set(first) | set(last) | measured)],
    }


@dataclass(frozen=True)
class EvidenceCardSlot:
    """One validated source selection for a predefined diagnostic-card slot."""

    slot: str
    role: str
    source_slice: int
    capture_frame: int | None
    selection: str
    abnormality_conspicuity: int | None = None
    attention_ids: tuple[str, ...] = ()
    geometry_group_id: str = ""
    parent_group_id: str = ""
    parent_group_members: tuple[int, ...] = ()


@dataclass(frozen=True)
class EvidenceStructureAttention:
    """Diagnosis-free structure metadata carried beside one evidence card."""

    attention_id: str
    structure: str
    assessment: str
    vertebra: str | None
    endplate_surface: str
    laterality: str
    confidence: str
    visual_salience: str
    within_study_priority: str
    slice_persistence: str
    observable_features: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class EvidenceFocus:
    """One allowlisted anatomical focus, independent of model wording."""

    focus_id: str
    level: str
    family: str
    confidence: str
    sources: tuple[str, ...]
    questions: tuple[str, ...]
    key_axial_frames: tuple[int, ...]
    attention_ids: tuple[str, ...] = ()
    geometry_anchor_lps: tuple[float, float, float] | None = None
    correspondence_status: str = ""
    visual_salience: str = "unspecified"
    within_study_priority: str = "unspecified"
    slice_persistence: str = "unspecified"
    card_slots: tuple[EvidenceCardSlot, ...] = ()
    structure_attention: tuple[EvidenceStructureAttention, ...] = ()
    card_kind: str = "level"


@dataclass(frozen=True)
class EvidencePlan:
    """Versioned local execution plan for focused-v2 composition."""

    schema_version: str
    focuses: tuple[EvidenceFocus, ...]
    level_frames: Dict[str, tuple[int, int]]
    warnings: tuple[str, ...]
    group_integrity: Dict[str, Any]


def normalize_level(value: Any) -> str:
    match = _LEVEL_PATTERN.search(str(value or ""))
    if not match:
        return ""
    return re.sub(r"\s*[-–—/]\s*", "-", match.group(1).upper())


def parse_level_map(screening_text: str) -> Dict[str, tuple[int, int]]:
    """Parse only the explicit level-map grammar emitted by the screening stage."""
    result: Dict[str, tuple[int, int]] = {}
    for match in _LEVEL_MAP_LINE.finditer(str(screening_text or "")):
        level = normalize_level(match.group(1))
        first = max(1, int(match.group(2)))
        last = max(first, int(match.group(3) or first))
        if level and level not in result:
            result[level] = (first, last)
    return result


def _text(value: Any, limit: int = 180) -> str:
    return " ".join(str(value or "").split())[:limit]


def _confidence(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"high", "moderate", "low"} else "low"


def _bounded_choice(value: Any, choices: set[str], default: str = "unspecified") -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in choices else default


def _visual_salience(value: Any) -> str:
    return _bounded_choice(value, {"subtle", "definite", "marked"})


def _within_study_priority(value: Any) -> str:
    return _bounded_choice(value, {"minor", "secondary", "major", "dominant"})


def _slice_persistence(value: Any) -> str:
    return _bounded_choice(
        value,
        {"single_slice", "two_adjacent_slices", "three_or_more_adjacent_slices"},
    )


def _family(candidate: Any, context_type: Any = "") -> str:
    token = str(candidate or "").strip().lower()
    if any(part in token for part in ("disc", "bulge", "protrusion", "extrusion")):
        return "disc_displacement"
    if any(part in token for part in ("canal", "recess", "foramin", "root", "cauda")):
        return "neural_compromise"
    if any(part in token for part in ("marrow", "modic", "endplate", "vertebral", "osteophyte")):
        return "osseous_endplate"
    if any(part in token for part in ("facet", "ligament", "synovial")):
        return "posterior_element"
    if any(part in token for part in ("listhesis", "alignment", "scoliosis")):
        return "alignment"
    context = str(context_type or "").strip().lower()
    if context in {"traumatic", "neoplastic", "postoperative", "inflammatory_or_infectious"}:
        return context
    if context in {"degenerative", "discogenic"}:
        return "degenerative"
    return "other"


def _screening_rows(structured: Optional[Dict[str, Any]]) -> Iterable[dict]:
    findings = (structured or {}).get("findings")
    if not isinstance(findings, list):
        return ()
    return (item for item in findings[:64] if isinstance(item, dict))


def _positive_frames(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    result = []
    for item in value[:5]:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return tuple(result)


def _context_rows(structured: Optional[Dict[str, Any]]) -> Iterable[dict]:
    rows = (structured or {}).get("context_attention_foci")
    if not isinstance(rows, list):
        return ()
    return (
        item
        for item in rows[:8]
        if isinstance(item, dict)
        and str(item.get("scope") or "").strip().lower() in {"regional", "level_specific"}
    )


def _structure_card_group(structure: Any) -> str:
    """Map one neutral screening anatomy to its independent diagnostic card."""
    value = str(structure or "").strip()
    if value == "disc":
        return "disc"
    if value in {"endplate", "bone_marrow", "vertebral_body"}:
        return "endplate_marrow"
    if value in {
        "central_canal", "lateral_recess", "nerve_root", "conus",
        "cauda_equina", "epidural_space",
    }:
        return "canal_neural"
    if value == "neural_foramen":
        return "foraminal"
    if value in {
        "posterior_element", "facet_joint", "ligamentum_flavum",
        "paraspinal_soft_tissue", "alignment", "other",
    }:
        return "posterior_elements"
    return "other"


def _card_slots_by_level(structured: Optional[Dict[str, Any]]) -> dict[str, tuple[EvidenceCardSlot, ...]]:
    templates = (structured or {}).get("level_card_templates")
    if not isinstance(templates, list):
        return {}
    result = {}
    for template in templates[:8]:
        if not isinstance(template, dict):
            continue
        level = normalize_level(template.get("level"))
        slots = template.get("slots")
        if not level or level in result or not isinstance(slots, list):
            continue
        accepted = []
        for raw in slots[: len(LEVEL_CARD_SLOT_ROLES)]:
            if not isinstance(raw, dict):
                continue
            slot = raw.get("slot")
            role = raw.get("role")
            source_slice = raw.get("source_slice")
            capture_frame = raw.get("capture_frame")
            if (
                slot not in LEVEL_CARD_SLOT_ROLES
                or role != LEVEL_CARD_SLOT_ROLES[slot]
                or type(source_slice) is not int
                or source_slice < 1
                or (capture_frame is not None and type(capture_frame) is not int)
            ):
                continue
            accepted.append(EvidenceCardSlot(
                slot=slot,
                role=role,
                source_slice=source_slice,
                capture_frame=capture_frame,
                selection="gemini_atlas_proposal",
                abnormality_conspicuity=(
                    raw.get("abnormality_conspicuity")
                    if type(raw.get("abnormality_conspicuity")) is int
                    and 0 <= raw["abnormality_conspicuity"] <= 3
                    else None
                ),
                attention_ids=tuple(
                    dict.fromkeys(
                        item for item in raw.get("attention_ids", ())
                        if isinstance(item, str)
                    )
                )[:8] if isinstance(raw.get("attention_ids"), list) else (),
                geometry_group_id=_text(raw.get("geometry_group_id"), 64),
                parent_group_id=_text(raw.get("parent_group_id"), 64),
                parent_group_members=tuple(
                    int(item) for item in raw.get("parent_group_members", ())
                    if type(item) is int and item > 0
                ) if isinstance(raw.get("parent_group_members"), list) else (),
            ))
        result[level] = tuple(accepted)
    return result


def build_evidence_plan(
    screening_text: str,
    screening_structured: Optional[Dict[str, Any]],
    context_structured: Optional[Dict[str, Any]],
    *,
    max_focuses: int = 4,
) -> EvidencePlan:
    """Merge screening and context attention without accepting executable orders."""
    grouped: Dict[tuple[str, str], dict] = {}
    warnings = []
    card_slots_by_level = _card_slots_by_level(screening_structured)

    for row in _screening_rows(screening_structured):
        if row.get("assessment") in ("normal", "not_assessable"):
            continue
        level = normalize_level(row.get("level"))
        additional_locations = []
        if not level:
            for location in row.get("locations", ()) if isinstance(row.get("locations"), list) else ():
                if not isinstance(location, dict):
                    continue
                role = location.get("pane")
                source_slice = location.get("source_slice")
                capture_frame = location.get("capture_frame")
                if (
                    role in {"sagittal_t2", "sagittal_t1", "axial_t2"}
                    and type(source_slice) is int and source_slice > 0
                    and (capture_frame is None or type(capture_frame) is int)
                ):
                    additional_locations.append((role, source_slice, capture_frame))
            if not additional_locations:
                warnings.append("screening_focus_without_allowlisted_level")
                continue
            level = ADDITIONAL_FINDINGS_LEVEL
        structure = row.get("structure")
        anatomical = isinstance(structure, str) and structure in STRUCTURES
        card_group = _structure_card_group(structure if anatomical else None)
        group_key = (level, card_group)
        entry = grouped.setdefault(
            group_key,
            {"families": [], "confidences": [], "sources": [], "questions": [],
             "attention_ids": [], "geometry_anchors": [], "correspondence_statuses": [],
             "visual_saliences": [], "within_study_priorities": [],
             "slice_persistences": [], "structure_attention": [],
             "additional_locations": []},
        )
        # Localization-only records use anatomy, never a diagnostic family.
        entry["families"].append(structure if anatomical else _family(row.get("candidate")))
        entry["confidences"].append(_confidence(row.get("confidence")))
        entry["visual_saliences"].append(_visual_salience(row.get("visual_salience")))
        entry["within_study_priorities"].append(
            _within_study_priority(row.get("within_study_priority"))
        )
        entry["slice_persistences"].append(_slice_persistence(row.get("slice_persistence")))
        entry["sources"].append("screening_candidate")
        attention_id = _text(row.get("attention_id"), 64)
        if attention_id:
            entry["attention_ids"].append(attention_id)
        observable_features = row.get("observable_features")
        observable_features = observable_features if isinstance(observable_features, dict) else {}
        entry["structure_attention"].append(EvidenceStructureAttention(
            attention_id=attention_id,
            structure=structure if anatomical else _family(row.get("candidate")),
            assessment="abnormal",
            vertebra=(str(row.get("vertebra")) if isinstance(row.get("vertebra"), str) else None),
            endplate_surface=_text(row.get("endplate_surface"), 24) or "not_applicable",
            laterality=_text(row.get("laterality"), 32) or "indeterminate",
            confidence=_confidence(row.get("confidence")),
            visual_salience=_visual_salience(row.get("visual_salience")),
            within_study_priority=_within_study_priority(row.get("within_study_priority")),
            slice_persistence=_slice_persistence(row.get("slice_persistence")),
            observable_features=tuple(
                sorted(
                    (str(name), str(value))
                    for name, value in observable_features.items()
                    if isinstance(name, str) and isinstance(value, str)
                )
            )[:8],
        ))
        if additional_locations:
            entry["additional_locations"].extend(
                (role, source_slice, capture_frame, attention_id)
                for role, source_slice, capture_frame in additional_locations
            )
        anchor = row.get("geometry_anchor_lps")
        if (
            isinstance(anchor, list)
            and len(anchor) == 3
            and all(type(value) in (int, float) and math.isfinite(value) for value in anchor)
        ):
            entry["geometry_anchors"].append(tuple(float(value) for value in anchor))
        geometry = row.get("geometry")
        if isinstance(geometry, dict) and isinstance(geometry.get("status"), str):
            entry["correspondence_statuses"].append(geometry["status"])
        note = "" if anatomical else _text(row.get("note"))
        if note:
            entry["questions"].append(note)
        key_frames = row.get("key_frames")
        if isinstance(key_frames, dict):
            entry.setdefault("key_axial_frames", []).extend(
                _positive_frames(key_frames.get("axial"))
            )

    for row in _context_rows(context_structured):
        level = normalize_level(row.get("anatomic_focus"))
        if not level:
            warnings.append("context_focus_without_allowlisted_level")
            continue
        matching_entries = [
            entry for (entry_level, _group), entry in grouped.items()
            if entry_level == level
        ]
        if not matching_entries:
            warnings.append("context_only_focus_not_carded")
            continue
        for entry in matching_entries:
            entry["families"].append(_family("", row.get("context_type")))
            entry["confidences"].append(_confidence(row.get("confidence")))
            entry["visual_saliences"].append("unspecified")
            entry["within_study_priorities"].append("unspecified")
            entry["slice_persistences"].append("unspecified")
            entry["sources"].append("context_attention_focus")
            questions = row.get("verification_questions")
            if isinstance(questions, list):
                entry["questions"].extend(
                    _text(item) for item in questions[:4] if _text(item)
                )

    confidence_rank = {"high": 0, "moderate": 1, "low": 2}
    family_rank = {
        "neoplastic": 0,
        "traumatic": 1,
        "inflammatory_or_infectious": 2,
        "disc_displacement": 3,
        "disc": 3,
        "neural_compromise": 4,
        "central_canal": 4,
        "lateral_recess": 4,
        "neural_foramen": 4,
        "nerve_root": 4,
        "postoperative": 5,
    }
    salience_rank = {"marked": 0, "definite": 1, "subtle": 2, "unspecified": 3}
    study_priority_rank = {
        "dominant": 0, "major": 1, "secondary": 2, "minor": 3, "unspecified": 4,
    }
    persistence_rank = {
        "three_or_more_adjacent_slices": 0,
        "two_adjacent_slices": 1,
        "single_slice": 2,
        "unspecified": 3,
    }
    correspondence_rank = {
        "verified_multiplanar": 0,
        "verified_multiseries_same_plane": 1,
        "verified_single_plane": 2,
        "frame_of_reference_unverified": 3,
        "": 3,
        "unavailable": 3,
        "same_plane_conflict": 4,
        "cross_plane_conflict": 4,
    }

    def strongest(entry: dict, key: str, ranking: dict[str, int]) -> str:
        return min(entry[key], key=lambda value: ranking.get(value, 99))

    def priority(
        item: tuple[tuple[str, str], dict],
    ) -> tuple[int, int, int, int, int, int, int, int]:
        (level, _card_group), entry = item
        confidence = min(entry["confidences"], key=lambda value: confidence_rank[value])
        family = min(entry["families"], key=lambda value: family_rank.get(value, 9))
        salience = strongest(entry, "visual_saliences", salience_rank)
        study_priority = strongest(
            entry, "within_study_priorities", study_priority_rank,
        )
        persistence = strongest(entry, "slice_persistences", persistence_rank)
        correspondence = min(
            entry.get("correspondence_statuses", ("",)) or ("",),
            key=lambda value: correspondence_rank.get(value, 99),
        )
        protected = int(not (salience == "marked" or study_priority == "dominant"))
        return (
            protected,
            salience_rank[salience],
            study_priority_rank[study_priority],
            persistence_rank[persistence],
            correspondence_rank.get(correspondence, 99),
            confidence_rank[confidence],
            family_rank.get(family, 9),
            _LEVEL_RANK.get(level, len(_LEVEL_RANK)),
        )

    ordered = sorted(grouped.items(), key=priority)
    limit = max(0, int(max_focuses))
    selected = ordered[:limit]
    focuses = []
    for ordinal, ((level, card_group), entry) in enumerate(selected, start=1):
        confidence = min(entry["confidences"], key=lambda value: confidence_rank[value])
        family = min(entry["families"], key=lambda value: family_rank.get(value, 9))
        salience = strongest(entry, "visual_saliences", salience_rank)
        study_priority = strongest(
            entry, "within_study_priorities", study_priority_rank,
        )
        persistence = strongest(entry, "slice_persistences", persistence_rank)
        additional_slots = ()
        if level == ADDITIONAL_FINDINGS_LEVEL:
            seen_locations = set()
            slots = []
            score_by_salience = {"subtle": 1, "definite": 2, "marked": 3}
            for role, source_slice, capture_frame, attention_id in entry.get(
                "additional_locations", ()
            ):
                identity = (role, source_slice, capture_frame, attention_id)
                if identity in seen_locations:
                    continue
                seen_locations.add(identity)
                slots.append(EvidenceCardSlot(
                    slot=f"additional.{len(slots) + 1:02d}",
                    role=role,
                    source_slice=source_slice,
                    capture_frame=capture_frame,
                    selection="screening_abnormal_location",
                    abnormality_conspicuity=score_by_salience.get(salience),
                    attention_ids=(attention_id,) if attention_id else (),
                ))
                if len(slots) == 9:
                    break
            additional_slots = tuple(slots)
        focuses.append(
            EvidenceFocus(
                focus_id=f"focus-{ordinal:02d}",
                level=level,
                family=family,
                confidence=confidence,
                sources=tuple(dict.fromkeys(entry["sources"])),
                questions=tuple(dict.fromkeys(entry["questions"]))[:4],
                key_axial_frames=tuple(
                    dict.fromkeys(entry.get("key_axial_frames", ()))
                )[:5],
                attention_ids=tuple(dict.fromkeys(entry.get("attention_ids", ())))[:8],
                geometry_anchor_lps=(
                    min(
                        entry.get("geometry_anchors", ()),
                        key=lambda first: sum(
                            math.dist(first, second)
                            for second in entry.get("geometry_anchors", ())
                        ),
                    )
                    if entry.get("geometry_anchors") else None
                ),
                correspondence_status=(
                    "verified_multiplanar"
                    if "verified_multiplanar" in entry.get("correspondence_statuses", ())
                    else next(iter(entry.get("correspondence_statuses", ())), "")
                ),
                visual_salience=salience,
                within_study_priority=study_priority,
                slice_persistence=persistence,
                card_slots=(
                    additional_slots
                    if level == ADDITIONAL_FINDINGS_LEVEL
                    else card_slots_by_level.get(level, ())
                ),
                structure_attention=tuple(entry.get("structure_attention", ()))[:16],
                card_kind=(
                    "additional_findings"
                    if level == ADDITIONAL_FINDINGS_LEVEL
                    else f"structure:{card_group}"
                ),
            )
        )

    if len(grouped) > len(focuses):
        warnings.append("focus_limit_applied")
        dropped = ordered[limit:]
        if any(
            strongest(entry, "within_study_priorities", study_priority_rank) == "dominant"
            for _key, entry in dropped
        ):
            warnings.append("dominant_focus_capacity_exceeded")
        if any(
            strongest(entry, "visual_saliences", salience_rank) == "marked"
            for _key, entry in dropped
        ):
            warnings.append("marked_focus_capacity_exceeded")
    return EvidencePlan(
        schema_version=SCHEMA_VERSION,
        focuses=tuple(focuses),
        level_frames=parse_level_map(screening_text),
        warnings=tuple(dict.fromkeys(warnings)),
        group_integrity=(
            dict(screening_structured.get("group_integrity") or {})
            if isinstance(screening_structured, dict) else {}
        ),
    )
