"""Anatomy-specific atomic screening and diagnostic-card contracts.

The general vision models do not own DICOM geometry. Gemini proposes bounded
abnormal anatomical foci in independent structure domains; local code validates
and merges those proposals. The diagnostic model receives one structure-specific
card per request. The final report is assembled from card-bound structured
decisions so one card cannot silently relabel or overwrite another card.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from modules.ai_imaging.eagle_eye.card_templates import list_card_templates

from .analysis_prompt import AnalysisStage
from .evidence_request import parse_level_map
from .llm_package import AnalysisPackage, PackagedImage


ATOMIC_PIPELINE_VERSION = "2.7.0"
ANATOMY_MAPPING_SCHEMA_VERSION = "1.10.0"
ATOMIC_SCREENING_SCHEMA_VERSION = "3.4.0"
ATOMIC_DIAGNOSIS_SCHEMA_VERSION = "1.2.0"
ATOMIC_SCREENING_MAX_OUTPUT_TOKENS = 24_000
ATOMIC_DIAGNOSIS_MAX_OUTPUT_TOKENS = 12_000

AXIAL_SIDE_CONTRACT = (
    "AXIAL RADIOLOGICAL DISPLAY: patient right is viewer left (R); "
    "patient left is viewer right (L). Use patient laterality in every answer. "
    "This rule applies to axial images, not sagittal panel order."
)

_VERTEBRAE = frozenset({"T12", "L1", "L2", "L3", "L4", "L5", "S1"})
_ENDPLATE_SURFACES = frozenset({"superior", "inferior", "both", "not_applicable"})
@dataclass(frozen=True)
class ScreeningDomain:
    key: str
    structures: tuple[str, ...]
    evidence_roles: tuple[str, ...]
    visual_task: str


@dataclass(frozen=True)
class ScreeningRequest:
    key: str
    structures: tuple[str, ...]
    evidence_roles: tuple[str, ...]
    visual_task: str


@dataclass(frozen=True)
class StructureCardProfile:
    key: str
    sagittal_planes: tuple[str, ...]
    sagittal_sequences: tuple[str, ...]
    axial_planes: tuple[str, ...]
    diagnostic_task: str
    template_id: str | None = None


_SCREENING_TEMPLATES = list_card_templates(
    modality="mri", body_part="lumbar_spine", family="screening"
)

SCREENING_DOMAINS = tuple(
    ScreeningDomain(
        template.key,
        template.anatomical_targets,
        template.required_sequences,
        template.model_instructions,
    )
    for template in _SCREENING_TEMPLATES
)

# Each task-specific screening template owns one card and one Gemini request.
# This keeps foramen assessment independent from facet/posterior-element review.
SCREENING_REQUESTS = tuple(
    ScreeningRequest(
        template.key,
        template.anatomical_targets,
        template.required_sequences,
        template.model_instructions,
    )
    for template in _SCREENING_TEMPLATES
)

_STRUCTURE_TO_GROUP = {
    structure: domain.key
    for domain in SCREENING_DOMAINS
    for structure in domain.structures
}


_DIAGNOSIS_TEMPLATES = list_card_templates(
    modality="mri", body_part="lumbar_spine", family="diagnosis"
)

STRUCTURE_CARD_PROFILES = {
    template.key: StructureCardProfile(
        template.key,
        tuple(f"{position}_plane" for position in template.sagittal_positions),
        tuple(
            sequence
            for sequence in template.required_sequences
            if sequence.startswith("sagittal_")
        ),
        tuple(f"{position}_plane" for position in template.axial_positions),
        template.model_instructions,
        template_id=template.template_id,
    )
    for template in _DIAGNOSIS_TEMPLATES
}
STRUCTURE_CARD_PROFILES["other"] = StructureCardProfile(
    "other",
    (
        "right_foraminal_plane",
        "right_paracentral_plane",
        "midline_plane",
        "left_paracentral_plane",
        "left_foraminal_plane",
    ),
    ("sagittal_t2", "sagittal_t1"),
    ("disc_level_plane", "max_abnormality_plane", "caudal_extent_plane"),
    "Classify only the abnormal structure explicitly bound to this additional-findings card.",
)


def structure_group(structure: Any) -> str:
    return _STRUCTURE_TO_GROUP.get(str(structure or "").strip(), "other")


def structures_for_group(group: Any) -> tuple[str, ...]:
    key = str(group or "").strip()
    for domain in SCREENING_DOMAINS:
        if domain.key == key:
            return domain.structures
    return ()


def anatomy_mapping_stage_for(base_stage: Any) -> AnalysisStage:
    """Create the anatomy-only Gate 1 prompt used before abnormality screening."""
    prompt = f"""ROLE - LUMBAR MRI ANATOMY MAPPING ONLY

This is Gate 1 of a three-gate pipeline. Use the complete correlated source
atlas to assign anatomical meaning to geometry-only series and slice groups.
Do not decide whether anything is normal or abnormal. Do not detect, name,
classify, grade, or prioritize pathology.

IDENTITY RULES
- Use exact cyan tile_id text printed on the atlas.
- The workstation supplies neutral series IDs and neutral axial group IDs. It
  establishes plane, slice order, patient right/left where reliable, physical
  coordinates, and which axial slices belong together. The workstation does not assign a lumbar level to a neutral axial group.
- Assign T1/T2 semantics to the neutral series from image appearance and the
  supplied metadata. A high-confidence semantic label is an explicit metadata
  prior. A low-confidence or unresolved series remains yours to identify.
- Select five distinct sagittal source planes in spatial order. Local DICOM LPS
  geometry, not the model, canonicalizes patient-right to patient-left order.
- Map every neutral sagittal geometry group exactly once to right_lateral,
  central, or left_lateral. Group IDs and slice membership are authoritative;
  assign anatomical meaning only after inspecting the images and metadata.
- Sagittal T1 and T2 roles must use the assigned series and closest
  geometry-matched planes.
- Map five ordered sagittal roles in each sequence: right foraminal, right
  paracentral, midline, left paracentral, and left foraminal.
- Map every neutral axial group independently to its anatomical level using visible
  anatomical landmarks and sagittal/axial relationships. Do not infer a level
  merely from group number or list position.
- Coverage can extend above T12-L1 (for example T11-T12) or below L5-S1.
  Adjacent thoracic disc labels T1-T2 through T11-T12 and S1-S2 are valid for
  anatomy mapping but outside the lumbar diagnostic scope. Keep their exact
  labels and group membership. Do not shift lumbar numbering to fit six levels.
  The workstation retains those groups as context, without diagnosing them.
- Inside each axial group, select three distinct representative samples for the
  disc-level, subarticular, and infrapedicular roles. The workstation verifies
  membership and records physical superior-to-inferior order but does not
  replace your anatomical role assignment with a Z-order shortcut.
- The measured group boundaries printed in the package are authoritative. Do
  not change their frame ranges, merge groups, or move a tile between groups.
- Anatomy labels apply to complete geometry groups. Representative plane choices
  describe roles inside a group and never redefine or shrink its membership.

Return exactly one compact JSON object and no prose, Markdown, code fence, or
reasoning. Use this exact contract:
{{
  "schema_version": "{ANATOMY_MAPPING_SCHEMA_VERSION}",
  "sequence_assignments": {{
    "sagittal_t2": {{"series_id": "<exact neutral series ID>", "confidence": "<high|moderate|low>"}},
    "sagittal_t1": {{"series_id": "<exact neutral series ID>", "confidence": "<high|moderate|low>"}},
    "axial_t2": {{"series_id": "<exact neutral series ID>", "confidence": "<high|moderate|low>"}}
  }},
  "sagittal_group_assignments": [
    {{
      "group_id": "<exact neutral sagittal group ID>",
      "anatomical_role": "<right_lateral|central|left_lateral>",
      "confidence": "<high|moderate|low>"
    }}
  ],
  "sagittal_planes": {{
    "sagittal_t2": {{
      "right_foraminal": "<exact sagittal T2 tile_id>",
      "right_paracentral": "<exact sagittal T2 tile_id>",
      "midline": "<exact sagittal T2 tile_id>",
      "left_paracentral": "<exact sagittal T2 tile_id>",
      "left_foraminal": "<exact sagittal T2 tile_id>"
    }},
    "sagittal_t1": {{
      "right_foraminal": "<exact sagittal T1 tile_id>",
      "right_paracentral": "<exact sagittal T1 tile_id>",
      "midline": "<exact sagittal T1 tile_id>",
      "left_paracentral": "<exact sagittal T1 tile_id>",
      "left_foraminal": "<exact sagittal T1 tile_id>"
    }}
  }},
  "axial_levels": [
    {{
      "axial_group_id": "<exact neutral axial group ID>",
      "level": "<one standard level name>",
      "axial_frames": ["<first frame integer>", "<last frame integer>"],
      "axial_planes": {{
        "disc_level": "<exact axial T2 tile_id>",
        "subarticular": "<exact axial T2 tile_id>",
        "infrapedicular": "<exact axial T2 tile_id>"
      }}
    }}
  ]
}}

Replace every angle-bracket placeholder with a source-grounded value. Return all
neutral sagittal groups exactly once, all five distinct sagittal source planes
in both sequences, and every neutral axial group exactly once. Anatomical level and
sagittal-group anatomical-role labels must each be unique. If a sequence, level,
group role, or slice role cannot be mapped without guessing, return an empty
string for that field so local code can reject the anatomy gate and stop the
analysis.
"""
    return AnalysisStage(
        id="lumbar_atomic_anatomy_mapping",
        name="anatomy_mapping",
        version=ATOMIC_PIPELINE_VERSION,
        label="Lumbar MRI anatomy mapping",
        text=prompt,
        model_feature=base_stage.model_feature,
        model_default=base_stage.model_default,
        temperature=getattr(base_stage, "temperature", 1.0),
        max_output_tokens=ATOMIC_SCREENING_MAX_OUTPUT_TOKENS,
    )


def screening_stage_for(base_stage: Any, request: ScreeningRequest) -> AnalysisStage:
    structures = ", ".join(request.structures)
    evidence = ", ".join(
        role.replace("_", " ").upper() for role in request.evidence_roles
    )
    canal_contract = ""
    canal_schema_line = ""
    screening_kind = "one high-sensitivity screening request"
    if request.key == "canal_neural":
        screening_kind = "one structure-specific screening request"
        canal_schema_line = (
            '  "central_canal_observations": ["<use the canal contract above>"],\n'
        )
        canal_contract = f"""

CENTRAL-CANAL SPECIFICITY CONTRACT
Assess the central canal independently from disc contour, lateral recesses,
foramina, and nerve-root effects. A disc abnormality or a small ventral thecal-sac
impression does not make the central canal abnormal when overall thecal-sac
caliber remains adequately patent. Treat that as a minor impression, not true
central-canal narrowing. A recess abnormality remains a separate
`lateral_recess` finding and must not be copied into `central_canal`.

For every mapped level, inspect the complete level-bound axial T2 group and the
central sagittal T2 context. First assess overall caliber and the relationship
of CSF to the cauda-equina rootlets. An abnormal central-canal finding requires
either reproducible meaningful caliber reduction on level-bound images or a
directly visible non-stenotic intracanal abnormality. Preserved CSF alone is not
an automatic veto when caliber is genuinely reduced, and the overview must not
override stronger axial evidence.

If CARD_METADATA_JSON contains `myelographic_context.status=included`, use its
MR-myelographic image only for level-to-level CSF-column/caliber comparison.
It is not a level localizer and cannot assign, move, or erase a finding by itself.
If it is absent, do not treat it as a protocol deficiency.

In addition to `findings`, return `central_canal_observations` with exactly one
row for every mapped axial level. This is an audit of the visual decision, not a
diagnosis, and it is not forwarded as a pathology finding:
  - level and axial_group_id: exact immutable Gate 1 values;
  - assessment: normal, abnormal, or not_assessable;
  - caliber: preserved, reduced, or indeterminate;
  - csf_visibility: preserved, partially_reduced, markedly_reduced, or indeterminate;
  - visual_basis: preserved_caliber, minor_impression_only,
    reproducible_caliber_reduction, other_intracanal_abnormality, or indeterminate;
  - myelographic_correlation: supports_reduction, preserved_column, discordant,
    not_available, or not_assessable;
  - axial_tile_ids: one to five exact tile IDs from that same axial group;
  - reason: at most 240 characters naming only the directly visible caliber/CSF
    feature that determined the assessment.

Consistency is mandatory: `minor_impression_only` and `preserved_caliber` are
normal central-canal decisions and may not emit a central_canal abnormality.
`reproducible_caliber_reduction` requires reduced caliber and an abnormal
central_canal finding. `other_intracanal_abnormality` may be abnormal with
preserved caliber, but the reason must identify the directly visible finding.
"""
    compartment_contract = ""
    if request.key in {"canal_neural", "foraminal"}:
        paired = "lateral_recess and nerve_root" if request.key == "canal_neural" else "neural_foramen"
        canal_schema_line += '  "compartment_observations": ["<use the paired-compartment contract above>"],\n'
        compartment_contract = f"""
PAIRED-COMPARTMENT COVERAGE CONTRACT
Lateral recesses belong to the spinal canal assessment. Central canal patency
does not establish recess or root normality. Foraminal status is assessed by
the separate foraminal card and retained alongside canal/recess status.
For every mapped diagnostic axial level, inspect {paired} on BOTH patient sides.
Return `compartment_observations`: exactly one row per level, structure and side:
level and axial_group_id: exact Gate 1 identities; structure: {paired};
laterality: right or left; assessment: normal, abnormal, or not_assessable;
tile_ids: one to five exact supplied tile IDs; reason: 1-240 characters describing
the visible basis. Recess/root rows require same-level axial evidence. Foraminal
rows may cite supplied sagittal images or same-level axial images.
Every abnormal row requires a separate matching `findings` entry with the same
level, structure and patient side (bilateral findings may cover both sides).
Normal rows must not contradict positive findings. Use not_assessable when the
compartment cannot be evaluated; never substitute normal or omit that row.
This checklist records observations only, without morphology or stenosis grading.
"""
    prompt = f"""ROLE - BOUNDED LUMBAR MRI ABNORMALITY SCREENING: {request.key.upper()}

{AXIAL_SIDE_CONTRACT}

This is Gate 2 of a three-gate pipeline and {screening_kind}
request in a five-request parallel pipeline. You receive exactly one
anatomy-only card plus its ANATOMY_MAP_JSON. Inspect ONLY these anatomical
structures: {structures}.
Ignore all other structures even when visibly abnormal; another independent
screening request owns them.

EVIDENCE ALLOWLIST
The evidence package intentionally contains only: {evidence}.
Use only those supplied sequence/plane roles. An excluded sequence is deliberate,
not a protocol deficiency, and must not be requested or treated as missing evidence.

CARD LAYOUT AUTHORITY
Physical whitespace and separate section rows are the primary geometry-group
signal. Section headers are secondary. Border or background color is tertiary
and must never be the only reason images are treated as one group. Never merge
tiles across a visible whitespace-separated geometry block.
Every displayed block contains the complete immutable source membership for that
screening task. Treat the printed group ID as atomic: do not split the block,
move one member to another level, or redefine a selected subset as a new group.

TASK
1. Decide whether a directly visible abnormality is present in an allowed structure.
2. Localize it by the immutable level/plane labels from Gate 1 and by exact
   printed tile_id. Do not recount or relabel lumbar levels.
3. Link the same abnormal focus across adjacent slices and across the supplied
   evidence roles only when anatomy and position plausibly match.
4. Record confidence, visual abnormality magnitude, within-study importance,
   persistence, and the source locations that demonstrate the same focus.

{request.visual_task}
{canal_contract}
{compartment_contract}

STRUCTURE-BY-STRUCTURE ABNORMALITY SWEEP
Inspect every allowed structure independently at every represented level. An
abnormal disc does not establish an abnormal canal, recess, root, or foramen;
and a normal-looking disc does not establish that those structures are normal.
If another allowed structure is visibly abnormal, emit a separate finding of
its own with its own evidence locations. Never embed a diagnostic consequence
or a normal/abnormal companion checklist inside a disc finding.

ENDPLATE IDENTITY
For an `endplate` finding, the vertebral anchor and the exact superior or
inferior surface are mandatory. `level` names the adjacent motion segment but
does not replace `vertebra` plus `endplate_surface`. For bone marrow or a
vertebral-body focus, name the exact vertebra and use `not_applicable` for the
surface. Never duplicate one focus under both neighboring motion segments.

Do not diagnose, classify, name a disease, assign a stenosis grade, describe
space effacement, label neural contact/displacement/compression, or infer a
clinical cause. Do not label a disc focus central, paracentral, subarticular,
foraminal, or extraforaminal. For `disc`, `central_canal`, `endplate`,
`bone_marrow`, and `vertebral_body`, use laterality=not_applicable. Laterality
is permitted only to identify an inherently paired anatomical structure such
as a recess, root, foramen, or facet; it is anatomical identity, not diagnosis.

For every focus use exact cyan tile_id text printed on the supplied anatomy card and
box_2d=[ymin,xmin,ymax,xmax] normalized 0..1000 within grayscale tile content.
List at most five decisive locations TOTAL per finding, including adjacent slices
and cross-plane correlation. Immediate neighboring slices establish persistence;
repeated T1/T2 views do not count as adjacent slices.

Return exactly one compact JSON object and no prose, Markdown, code fence, or
reasoning. Use this exact field contract:

{{
  "schema_version": "{ATOMIC_SCREENING_SCHEMA_VERSION}",
  "screening_request": "{request.key}",
{canal_schema_line}  "findings": [
    {{
      "structure": "<one allowed structure>",
      "assessment": "abnormal",
      "level": "<T12-L1|L1-L2|L2-L3|L3-L4|L4-L5|L5-S1|unclear>",
      "vertebra": "<T12|L1|L2|L3|L4|L5|S1|null>",
      "endplate_surface": "<superior|inferior|both|not_applicable>",
      "laterality": "<left|right|bilateral|indeterminate|not_applicable>",
      "confidence": "<high|moderate|low>",
      "visual_salience": "<marked|definite|subtle>",
      "within_study_priority": "<dominant|major|secondary|minor>",
      "slice_persistence": "<single_slice|two_adjacent_slices|three_or_more_adjacent_slices>",
      "locations": [
        {{"image": 1, "tile_id": "<exact printed tile_id>",
          "box_2d": [100, 100, 200, 200]}}
      ]
    }}
  ]
}}

The numeric values above show syntax only. Do not return a level map; Gate 1 is
the sole anatomical-map authority. Use only the supplied anatomy card. Omit
normal structures. Use assessment=not_assessable only when image quality
prevents a decision. If no allowed abnormality is visible, return an empty
findings array.
"""
    return AnalysisStage(
        id=f"lumbar_atomic_screening_{request.key}",
        name=f"screening_{request.key}",
        version=ATOMIC_PIPELINE_VERSION,
        label=f"Lumbar MRI bounded screening - {request.key}",
        text=prompt,
        model_feature=base_stage.model_feature,
        model_default=base_stage.model_default,
        temperature=getattr(base_stage, "temperature", 1.0),
        # Gemini reasoning tokens share this allowance with the visible JSON.
        # A 6k ceiling could expire while the model was still emitting the map,
        # leaving no parseable findings. Keep the task compact but leave bounded
        # headroom for the provider's internal reasoning budget.
        max_output_tokens=ATOMIC_SCREENING_MAX_OUTPUT_TOKENS,
    )


def _image_role(image: PackagedImage) -> str:
    session = str(image.session or "").lower()
    for role in ("sagittal_t2", "sagittal_t1", "axial_t2"):
        if role in session:
            return role
    return ""


def screening_package_for(package: AnalysisPackage, request: ScreeningRequest) -> AnalysisPackage:
    selected_pages = [
        page
        for page in package.evidence_audit.get("pages", ())
        if isinstance(page, dict) and page.get("role") in request.evidence_roles
    ]
    images_by_index = {image.index: image for image in package.images}
    images = []
    pages = []
    for new_index, page in enumerate(selected_pages, start=1):
        original_index = page.get("image_index")
        image = images_by_index.get(original_index)
        if image is None:
            continue
        page_copy = dict(page)
        page_copy["image_index"] = new_index
        page_copy["tiles"] = [
            dict(tile, image_index=new_index)
            for tile in page.get("tiles", ()) if isinstance(tile, dict)
        ]
        pages.append(page_copy)
        images.append(PackagedImage(
            image.path,
            image.caption,
            image.session,
            new_index,
            capture=image.capture,
            source_path=image.source_path,
            evidence_mode=image.evidence_mode,
            card_payload=image.card_payload,
        ))
    if not images and not package.evidence_audit.get("pages"):
        images = [
            PackagedImage(
                image.path, image.caption, image.session, index,
                capture=image.capture, source_path=image.source_path,
                evidence_mode=image.evidence_mode, card_payload=image.card_payload,
            )
            for index, image in enumerate(
                (
                    image for image in package.images
                    if _image_role(image) in request.evidence_roles
                ),
                start=1,
            )
        ]
    audit = dict(package.evidence_audit)
    if "pages" in audit:
        audit["pages"] = pages
    audit["atomic_screening_request"] = request.key
    audit["atomic_screening_evidence_roles"] = list(request.evidence_roles)
    return AnalysisPackage(
        package.session_dir,
        package.session_id,
        package.protocol_id,
        package.analysis,
        package.header
        + "\n  BOUNDED SCREENING REQUEST: "
        + request.key
        + ". Only the request structures in the system prompt are in scope.",
        images,
        study_instance_uid=package.study_instance_uid,
        source_series=package.source_series,
        evidence_audit=audit,
    )


def _format_level_map(levels: dict[str, tuple[int, int]]) -> str:
    if not levels:
        return "LEVEL MAP\n  Not supplied"
    return "LEVEL MAP\n" + "\n".join(
        f"  {level}: axial frames {bounds[0]}-{bounds[1]}"
        for level, bounds in levels.items()
    )


def _structured_level_map(structured: Any) -> dict[str, tuple[int, int]]:
    rows = structured.get("level_map") if isinstance(structured, dict) else None
    if not isinstance(rows, list):
        return {}
    result: dict[str, tuple[int, int]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level") or "").strip()
        frames = row.get("axial_frames")
        if not level or not isinstance(frames, (list, tuple)) or len(frames) != 2:
            continue
        try:
            first, last = int(frames[0]), int(frames[1])
        except (TypeError, ValueError):
            continue
        if first > 0 and last >= first:
            result[level] = (first, last)
    return result


def screening_outcome_errors(
    request: ScreeningRequest, outcome: dict[str, Any], package: AnalysisPackage | None = None,
) -> list[str]:
    """Return contract errors that make one Gate 2 response unusable."""
    structured = outcome.get("structured") if isinstance(outcome, dict) else None
    if not isinstance(structured, dict):
        return ["unstructured_response"]
    errors = []
    if str(structured.get("schema_version") or "") != ATOMIC_SCREENING_SCHEMA_VERSION:
        errors.append("schema_version")
    if str(structured.get("screening_request") or "") != request.key:
        errors.append("screening_request")
    findings = structured.get("findings")
    if not isinstance(findings, list):
        errors.append("findings_not_list")
        return errors
    allowed = set(request.structures)
    forbidden_fields = (
        "observable_features", "companion_review", "diagnosis", "morphology",
        "zone", "grade", "space_effacement", "neural_relationship",
    )
    neutral_laterality_structures = {
        "disc", "central_canal", "endplate", "bone_marrow", "vertebral_body",
    }
    paired_lateralities = {
        "left", "right", "bilateral", "indeterminate", "not_applicable",
    }
    for index, row in enumerate(findings[:32]):
        if not isinstance(row, dict):
            errors.append(f"finding_{index + 1}_not_object")
            continue
        if str(row.get("structure") or "") not in allowed:
            errors.append(f"finding_{index + 1}_structure")
        if str(row.get("assessment") or "") not in {"abnormal", "not_assessable"}:
            errors.append(f"finding_{index + 1}_assessment")
        structure = str(row.get("structure") or "")
        laterality = str(row.get("laterality") or "")
        if structure in allowed and structure in neutral_laterality_structures:
            if laterality != "not_applicable":
                errors.append(f"finding_{index + 1}_laterality")
        elif structure in allowed and laterality not in paired_lateralities:
            errors.append(f"finding_{index + 1}_laterality")
        for field in forbidden_fields:
            if field in row:
                errors.append(
                    f"finding_{index + 1}_forbidden_diagnostic_field_{field}"
                )
        if structure in {"endplate", "bone_marrow", "vertebral_body"}:
            if str(row.get("vertebra") or "") not in _VERTEBRAE:
                errors.append(f"finding_{index + 1}_vertebra")
            surface = str(row.get("endplate_surface") or "")
            if surface not in _ENDPLATE_SURFACES:
                errors.append(f"finding_{index + 1}_endplate_surface")
            elif structure == "endplate" and surface == "not_applicable":
                errors.append(f"finding_{index + 1}_endplate_surface")
            elif structure != "endplate" and surface != "not_applicable":
                errors.append(f"finding_{index + 1}_endplate_surface")
    if len(findings) > 32:
        errors.append("finding_count")
    if request.key == "canal_neural":
        errors.extend(_canal_observation_errors(structured, package))
    if request.key in {"canal_neural", "foraminal"}:
        errors.extend(_compartment_observation_errors(request, structured, package))
    return errors


def _compartment_observation_errors(
    request: ScreeningRequest, structured: dict[str, Any], package: AnalysisPackage | None,
) -> list[str]:
    """Reject missing, contradictory or foreign-level paired neural observations."""
    rows = structured.get("compartment_observations")
    if not isinstance(rows, list) or not rows:
        return ["compartment_observations_missing"]
    structures = ("lateral_recess", "nerve_root") if request.key == "canal_neural" else ("neural_foramen",)
    expected = {}
    tiles = {}
    sagittal_sides = {}
    if package is not None:
        sagittal_sides = {
            row.get("group_id"): row.get("anatomical_role")
            for row in (package.evidence_audit.get("anatomy_map") or {}).get("sagittal_group_assignments", ())
            if isinstance(row, dict)
        }
        expected = {
            str(row.get("level")): str(row.get("axial_group_id"))
            for row in (package.evidence_audit.get("anatomy_map") or {}).get("axial_levels", ())
            if isinstance(row, dict)
        }
        tiles = {
            str(tile.get("tile_id")): tile
            for page in package.evidence_audit.get("pages", ()) if isinstance(page, dict)
            for tile in page.get("tiles", ()) if isinstance(tile, dict)
        }
    # Standalone contract checks can infer coverage; runtime always supplies its map.
    levels = set(expected) or {
        str(row.get("level") or "") for row in
        [*rows, *(structured.get("central_canal_observations") or ()), *structured.get("findings", ())]
        if isinstance(row, dict)
    }
    required = {(level, structure, side) for level in levels
                for structure in structures for side in ("right", "left")}
    errors, seen = [], set()
    findings = [row for row in structured.get("findings", ()) if isinstance(row, dict)]
    for row in rows:
        if not isinstance(row, dict):
            errors.append("compartment_observation_not_object")
            continue
        level, structure, side = (str(row.get(key) or "") for key in ("level", "structure", "laterality"))
        key = (level, structure, side)
        if key not in required or key in seen or not level:
            errors.append(f"compartment_observation_identity:{level}:{structure}:{side}")
        seen.add(key)
        assessment = row.get("assessment")
        if assessment not in {"normal", "abnormal", "not_assessable"}:
            errors.append(f"compartment_observation_assessment:{level}")
        if not isinstance(row.get("reason"), str) or not 1 <= len(row["reason"].strip()) <= 240:
            errors.append(f"compartment_observation_reason:{level}")
        ids = row.get("tile_ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 5 or any(not isinstance(t, str) or not t for t in ids):
            errors.append(f"compartment_observation_evidence:{level}")
            ids = []
        if expected:
            group = expected.get(level)
            def permitted(tile_id: str) -> bool:
                tile = tiles.get(tile_id, {})
                if tile.get("role") == "axial_t2":
                    return tile.get("geometry_group_id") == group
                return (request.key == "foraminal" and tile.get("role") in {"sagittal_t1", "sagittal_t2"}
                        and sagittal_sides.get(tile.get("geometry_group_id")) == f"{side}_lateral")
            if row.get("axial_group_id") != group or not all(permitted(t) for t in ids):
                errors.append(f"compartment_observation_wrong_group_evidence:{level}")
        matching = [f for f in findings if f.get("level") == level and f.get("structure") == structure
                    and f.get("laterality") in (side, "bilateral")]
        positive = any(f.get("assessment") == "abnormal" for f in matching)
        if (assessment == "abnormal") != positive or (
            assessment == "normal" and any(f.get("assessment") == "not_assessable" for f in matching)
        ):
            errors.append(f"compartment_observation_finding_conflict:{level}:{structure}:{side}")
    if seen != required:
        errors.append("compartment_observation_level_side_coverage")
    for finding in findings:
        if finding.get("structure") in structures and finding.get("laterality") not in {"right", "left", "bilateral"}:
            errors.append("compartment_observation_finding_side_unresolved")
    return list(dict.fromkeys(errors))


def _canal_observation_errors(
    structured: dict[str, Any], package: AnalysisPackage | None,
) -> list[str]:
    observations = structured.get("central_canal_observations")
    if not isinstance(observations, list) or not observations:
        return ["canal_observations_missing"]
    errors = []
    allowed = {
        "assessment": {"normal", "abnormal", "not_assessable"},
        "caliber": {"preserved", "reduced", "indeterminate"},
        "csf_visibility": {"preserved", "partially_reduced", "markedly_reduced", "indeterminate"},
        "visual_basis": {"preserved_caliber", "minor_impression_only", "reproducible_caliber_reduction", "other_intracanal_abnormality", "indeterminate"},
        "myelographic_correlation": {"supports_reduction", "preserved_column", "discordant", "not_available", "not_assessable"},
    }
    central_rows = [
        row
        for row in structured.get("findings") or ()
        if isinstance(row, dict) and row.get("structure") == "central_canal"
        and row.get("assessment") == "abnormal"
    ]
    central_positive = {str(row.get("level") or "") for row in central_rows}
    for level in central_positive:
        if sum(str(row.get("level") or "") == level for row in central_rows) != 1:
            errors.append(f"canal_observation_finding_count:{level}")
    expected: dict[str, tuple[str, set[str]]] = {}
    if package is not None:
        anatomy_map = package.evidence_audit.get("anatomy_map") or {}
        page_tiles = [
            tile for page in package.evidence_audit.get("pages", ())
            if isinstance(page, dict) for tile in page.get("tiles", ())
            if isinstance(tile, dict)
        ]
        for row in anatomy_map.get("axial_levels") or ():
            if not isinstance(row, dict):
                continue
            level, group = str(row.get("level") or ""), str(row.get("axial_group_id") or "")
            tiles = {
                str(tile.get("tile_id") or "") for tile in page_tiles
                if tile.get("geometry_group_id") == group and tile.get("role") == "axial_t2"
            }
            expected[level] = (group, tiles)
        context = next((
            image.card_payload.get("anatomy_card", {}).get("myelographic_context", {})
            for image in package.images
            if isinstance(image.card_payload, dict)
        ), {})
        myelography_included = context.get("status") == "included"
    else:
        myelography_included = None
    seen = set()
    for index, row in enumerate(observations):
        if not isinstance(row, dict):
            errors.append(f"canal_observation_{index + 1}_not_object")
            continue
        level = str(row.get("level") or "")
        if not level or level in seen:
            errors.append(f"canal_observation_level:{level or index + 1}")
        seen.add(level)
        for field, values in allowed.items():
            if str(row.get(field) or "") not in values:
                errors.append(f"canal_observation_{field}:{level}")
        reason = str(row.get("reason") or "")
        if not reason or len(reason) > 240:
            errors.append(f"canal_observation_reason:{level}")
        tile_ids = row.get("axial_tile_ids")
        if not isinstance(tile_ids, list) or not 1 <= len(tile_ids) <= 5:
            errors.append(f"canal_observation_evidence:{level}")
            tile_ids = []
        if level in expected:
            group, permitted = expected[level]
            if str(row.get("axial_group_id") or "") != group or any(
                str(tile_id) not in permitted for tile_id in tile_ids
            ):
                errors.append(f"canal_observation_wrong_group_evidence:{level}")
        assessment = str(row.get("assessment") or "")
        caliber = str(row.get("caliber") or "")
        basis = str(row.get("visual_basis") or "")
        correlation = str(row.get("myelographic_correlation") or "")
        if basis in {"preserved_caliber", "minor_impression_only"} and (
            assessment != "normal" or caliber != "preserved" or level in central_positive
        ):
            errors.append(f"canal_observation_finding_conflict:{level}")
        if basis == "reproducible_caliber_reduction" and (
            assessment != "abnormal" or caliber != "reduced" or level not in central_positive
        ):
            errors.append(f"canal_observation_finding_conflict:{level}")
        if assessment == "abnormal" and level not in central_positive:
            errors.append(f"canal_observation_finding_conflict:{level}")
        if assessment == "normal" and level in central_positive:
            errors.append(f"canal_observation_finding_conflict:{level}")
        if level in central_positive and basis not in {
            "reproducible_caliber_reduction", "other_intracanal_abnormality",
        }:
            errors.append(f"canal_observation_finding_conflict:{level}")
        if myelography_included is True and correlation == "not_available":
            errors.append(f"canal_observation_myelography_status:{level}")
        if myelography_included is False and correlation in {
            "supports_reduction", "preserved_column", "discordant",
        }:
            errors.append(f"canal_observation_myelography_status:{level}")
    if expected and seen != set(expected):
        errors.append("canal_observation_level_coverage")
    return list(dict.fromkeys(errors))


def merge_screening_outcomes(
    outcomes: Sequence[tuple[ScreeningRequest, dict[str, Any]]],
    anatomy_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge independent structure screens without accepting cross-domain rows."""
    findings: list[dict[str, Any]] = []
    warnings: list[str] = []
    context_levels = (anatomy_map or {}).get("context_axial_levels") or []
    if context_levels:
        warnings.append(
            "Outside lumbar diagnostic scope: "
            + ", ".join(str(row["level"]) for row in context_levels)
            + ". Source images and anatomy mapping retained; pathology was not assessed."
        )
    maps: list[tuple[str, dict[str, tuple[int, int]]]] = []
    domain_audit = []
    neural_coverage = []
    request_indices = {
        request.key: index for index, request in enumerate(SCREENING_REQUESTS, start=1)
    }
    for request, outcome in outcomes:
        structured = outcome.get("structured") if isinstance(outcome, dict) else None
        answer = str(outcome.get("answer") or "") if isinstance(outcome, dict) else ""
        level_map = _structured_level_map(structured) or parse_level_map(answer)
        if level_map:
            maps.append((request.key, level_map))
        accepted = 0
        rows = structured.get("findings") if isinstance(structured, dict) else None
        if not isinstance(rows, list):
            warnings.append(f"atomic_screening_unstructured:{request.key}")
            domain_audit.append({"domain": request.key, "status": "unavailable", "finding_count": 0})
            continue
        allowed = set(request.structures)
        for raw in rows[:32]:
            if not isinstance(raw, dict):
                continue
            if raw.get("structure") not in allowed:
                warnings.append(f"atomic_screening_cross_domain_row:{request.key}")
                continue
            if any(raw.get("level") == row["level"] for row in context_levels):
                warnings.append(f"atomic_screening_outside_lumbar_scope:{raw.get('level')}")
                continue
            row = dict(raw)
            if anatomy_map:
                locations = []
                for location in row.get("locations") or ():
                    if not isinstance(location, dict):
                        continue
                    mapped = dict(location)
                    if mapped.get("image") == 1:
                        mapped["image"] = request_indices[request.key]
                    locations.append(mapped)
                row["locations"] = locations
            row["screening_request"] = request.key
            row["screening_domain"] = structure_group(row.get("structure"))
            findings.append(row)
            accepted += 1
        domain_record = {
            "domain": request.key, "status": "available", "finding_count": accepted,
        }
        if request.key == "canal_neural":
            domain_record["central_canal_observations"] = [
                dict(row) for row in structured.get("central_canal_observations") or ()
                if isinstance(row, dict)
            ]
            neural_coverage.extend(
                dict(row, structure="central_canal", laterality="not_applicable")
                for row in domain_record["central_canal_observations"]
            )
        if request.key in {"canal_neural", "foraminal"}:
            domain_record["compartment_observations"] = [
                dict(row) for row in structured.get("compartment_observations") or ()
                if isinstance(row, dict)
            ]
            neural_coverage.extend(domain_record["compartment_observations"])
        domain_audit.append(domain_record)

    for row in neural_coverage:
        if row.get("assessment") == "not_assessable":
            warnings.append(
                f"neural_compartment_not_assessable:{row.get('level')}:{row.get('structure')}:{row.get('laterality')}"
            )
    authoritative_map: dict[str, tuple[int, int]] = {}
    if anatomy_map:
        for row in anatomy_map.get("axial_levels") or ():
            if not isinstance(row, dict):
                continue
            frames = row.get("axial_frames")
            if isinstance(frames, (list, tuple)) and len(frames) == 2:
                authoritative_map[str(row.get("level") or "")] = (
                    int(frames[0]), int(frames[1])
                )
    else:
        for key, level_map in maps:
            if key == "disc":
                authoritative_map = level_map
                break
        if not authoritative_map and maps:
            authoritative_map = maps[0][1]
        if authoritative_map and any(
            level_map != authoritative_map for _key, level_map in maps
        ):
            warnings.append("atomic_screening_level_map_conflict")

    structured = {
        "schema_version": ATOMIC_SCREENING_SCHEMA_VERSION,
        "atomic_pipeline_version": ATOMIC_PIPELINE_VERSION,
        "level_map": [
            {"level": level, "axial_frames": [bounds[0], bounds[1]]}
            for level, bounds in authoritative_map.items()
        ],
        "findings": findings,
        "level_card_templates": [],
        "group_integrity": (
            dict(anatomy_map.get("group_integrity") or {}) if anatomy_map else {}
        ),
        "atomic_screening": domain_audit,
        "neural_compartment_coverage": neural_coverage,
        "anatomy_coverage": dict((anatomy_map or {}).get("coverage") or {}),
        "anatomy_gate": {
            "schema_version": ANATOMY_MAPPING_SCHEMA_VERSION,
            "status": "validated" if anatomy_map else "legacy_or_unavailable",
        },
        "warnings": list(dict.fromkeys(warnings)),
    }
    answer = (
        _format_level_map(authoritative_map)
        + "\n\nSCREENING ATTENTION\n```json\n"
        + json.dumps(structured, ensure_ascii=False, indent=2)
        + "\n```"
    )
    return {"answer": answer, "structured": structured, "warnings": structured["warnings"]}


def verification_stage_for(base_stage: Any, group: str) -> AnalysisStage:
    profile = STRUCTURE_CARD_PROFILES.get(group, STRUCTURE_CARD_PROFILES["other"])
    allowed_structures = structures_for_group(profile.key) or ("other",)
    if len(allowed_structures) == 1:
        structure_field = f'"structure": "{allowed_structures[0]}",'
    else:
        structure_field = (
            '"structure": "<exactly one of: '
            + "|".join(allowed_structures)
            + '>",'
        )
    prompt = f"""ROLE - ATOMIC LUMBAR MRI DIAGNOSIS: {profile.key.upper()}

{AXIAL_SIDE_CONTRACT}

You receive exactly one structure-specific card and its immediately preceding
CARD_METADATA_JSON. This is one independent diagnostic decision. Bind card_id,
subject_level, structure_group, attention IDs, source frames, and patient
orientation before reading the pixels. Do not inspect another level outside the card.
Do not inherit diagnosis, side, severity, or normality from screening metadata.

DIAGNOSTIC TASK
{profile.diagnostic_task}

Use the available planes as complementary evidence, not as a vote. Trace one
lesion through neighboring slices. If planes disagree, determine whether they
sample different parts of the same three-dimensional abnormality; otherwise
return INDETERMINATE. A normal variant or artifact is an allowed conclusion.
Clinical context may prioritize a differential but cannot override visible
morphology, level, side, or severity. Do not create findings outside the card.

DISPOSITION SEMANTICS
CONFIRMED means the candidate's abnormal presence and anatomical localization
are independently supported. REFINED means the abnormality is supported but its
screening localization, side, or anatomical identity required correction;
REFINED does not mean merely that a diagnosis was assigned. REJECTED means
normal anatomy, non-pathological variation, artifact, partial volume, or
insufficient objective abnormality. INDETERMINATE means the card cannot decide.
Every positive decision must cite confirming and contradicting evidence.

Return exactly one JSON object and no prose:
{{
  "schema_version": "{ATOMIC_DIAGNOSIS_SCHEMA_VERSION}",
  "card_id": "<exact card_id>",
  "subject_level": "<exact subject level or null>",
  "structure_group": "{profile.key}",
  "verifications": [
    {{
      "candidate": "<exact bound attention_id>",
      "card_id": "<exact card_id>",
      "structure_group": "{profile.key}",
      "level": "<exact subject level or unclear>",
      {structure_field}
      "vertebra": "<T12|L1|L2|L3|L4|L5|S1|null>",
      "endplate_surface": "<superior|inferior|both|not_applicable>",
      "status": "<CONFIRMED|REFINED|REJECTED|INDETERMINATE|ADDED>",
      "final_diagnosis": "<diagnosis or null>",
      "laterality": "<left|right|bilateral|central|indeterminate|not_applicable>",
      "refined_finding": "<one concise report-ready card-bound finding or null>",
      "reason": "<decisive and contradicting card evidence with exact frame or slot IDs>",
      "grade_system": null,
      "grade": null,
      "decided_on": ["<exact slot or frame identity>"]
    }}
  ],
  "limitations": ["<card-bound assessment limitation>"],
  "not_assessable": ["<card-bound structure and reason>"]
}}

Emit one decision for every attention ID bound to this card. REJECTED and
INDETERMINATE require refined_finding=null. Do not mention a diagnosis in the
reason unless it is the result of your independent card read.
"""
    return AnalysisStage(
        id=f"lumbar_atomic_verification_{profile.key}",
        name=f"verification_{profile.key}",
        version=ATOMIC_PIPELINE_VERSION,
        label=f"Lumbar MRI atomic diagnosis - {profile.key}",
        text=prompt,
        model_feature=base_stage.model_feature,
        model_default=base_stage.model_default,
        temperature=getattr(base_stage, "temperature", 1.0),
        max_output_tokens=ATOMIC_DIAGNOSIS_MAX_OUTPUT_TOKENS,
    )


def verification_package_for(package: AnalysisPackage, image_index: int) -> AnalysisPackage:
    image = package.images[image_index - 1]
    payload = image.card_payload if isinstance(image.card_payload, dict) else {}
    metadata = payload.get("card_metadata") if isinstance(payload, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    binding = None
    for item in package.evidence_audit.get("card_bindings", ()):
        if isinstance(item, dict) and item.get("image_index") == image_index:
            binding = dict(item)
            break
    audit = dict(package.evidence_audit)
    audit["card_bindings"] = [binding] if binding else []
    audit["atomic_card_image_index"] = image_index
    group = str(metadata.get("structure_group") or metadata.get("card_group") or "other")
    context_markers = (
        "CLINICAL CONTEXT EXTRACTED BY THE PARALLEL MULTI-SOURCE READER.",
        "CLINICAL CONTEXT RESPONSE UNUSABLE.", "CLINICAL CONTEXT BRANCH UNAVAILABLE.",
        "NO CLINICAL CONTEXT DOCUMENT",
    )
    context_offsets = [package.header.find(marker) for marker in context_markers if marker in package.header]
    clinical_context = package.header[min(context_offsets):] if context_offsets else ""
    header = (
        "ATOMIC STRUCTURE CARD REQUEST\n"
        f"  ORIGINAL IMAGE INDEX: {image_index}\n"
        f"  CARD ID: {metadata.get('card_id') or 'unassigned'}\n"
        f"  SUBJECT LEVEL: {metadata.get('subject_level') or 'unassigned'}\n"
        f"  STRUCTURE GROUP: {group}\n"
        "  This request contains exactly one diagnostic card. No other card, level, "
        "or structure may be inferred.\n\n"
        + AXIAL_SIDE_CONTRACT + "\n"
        + "CARD LAYOUT AUTHORITY: use the supplied card's printed panel labels and CARD_METADATA_JSON.\n"
        + clinical_context
    )
    return AnalysisPackage(
        package.session_dir,
        package.session_id,
        package.protocol_id,
        package.analysis,
        header,
        [image],
        study_instance_uid=package.study_instance_uid,
        source_series=package.source_series,
        evidence_audit=audit,
    )


def card_group(package: AnalysisPackage, image_index: int) -> str:
    image = package.images[image_index - 1]
    payload = image.card_payload if isinstance(image.card_payload, dict) else {}
    metadata = payload.get("card_metadata") if isinstance(payload, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    return str(metadata.get("structure_group") or metadata.get("card_group") or "other")


def validate_verification_outcome(
    package: AnalysisPackage, image_index: int, outcome: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Enforce card identity before any independent result enters the merge."""
    image = package.images[image_index - 1]
    payload = image.card_payload if isinstance(image.card_payload, dict) else {}
    metadata = payload.get("card_metadata") if isinstance(payload, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    expected_card = str(metadata.get("card_id") or "")
    expected_level = str(metadata.get("subject_level") or "unclear")
    expected_group = str(metadata.get("structure_group") or "other")
    expected_attention = [str(value) for value in metadata.get("attention_ids") or ()]
    allowed_structures = set(structures_for_group(expected_group) or ("other",))
    expected_structure_by_attention = {
        str(item.get("attention_id")): str(item.get("structure"))
        for item in metadata.get("structures") or ()
        if isinstance(item, dict)
        and item.get("attention_id") is not None
        and str(item.get("structure") or "") in allowed_structures
    }
    structured = outcome.get("structured") if isinstance(outcome, dict) else None
    rows = structured.get("verifications") if isinstance(structured, dict) else None
    if not isinstance(rows, list):
        return outcome, [f"atomic_verification_unstructured:{expected_card}"]

    warnings = []
    if (
        str(structured.get("card_id") or "") != expected_card
        or str(structured.get("subject_level") or "") != expected_level
        or str(structured.get("structure_group") or "") != expected_group
    ):
        warnings.append(f"atomic_verification_envelope_conflict:{expected_card}")
    accepted = []
    decided = set()
    allowed_statuses = {"CONFIRMED", "REFINED", "REJECTED", "INDETERMINATE", "ADDED"}
    for raw in rows[:16]:
        if not isinstance(raw, dict):
            warnings.append(f"atomic_verification_invalid_row:{expected_card}")
            continue
        candidate = raw.get("candidate")
        status = str(raw.get("status") or "")
        if (
            str(raw.get("card_id") or "") != expected_card
            or str(raw.get("structure_group") or "") != expected_group
            or str(raw.get("level") or "") != expected_level
        ):
            warnings.append(f"atomic_verification_identity_conflict:{expected_card}")
            continue
        if candidate is not None and str(candidate) not in expected_attention:
            warnings.append(f"atomic_verification_candidate_unbound:{expected_card}")
            continue
        if candidate is None:
            warnings.append(f"atomic_verification_candidate_missing:{expected_card}")
            continue
        structure = str(raw.get("structure") or "")
        expected_structure = expected_structure_by_attention.get(str(candidate))
        if structure not in allowed_structures or (
            expected_structure is not None and structure != expected_structure
        ):
            warnings.append(f"atomic_verification_structure_invalid:{expected_card}")
            continue
        if status not in allowed_statuses:
            warnings.append(f"atomic_verification_status_invalid:{expected_card}")
            continue
        if candidate is not None and str(candidate) in decided:
            warnings.append(f"atomic_verification_candidate_duplicate:{expected_card}")
            continue
        row = dict(raw)
        if (
            expected_group == "endplate_marrow"
            and status in {"CONFIRMED", "REFINED", "ADDED"}
            and str(row.get("structure") or "") == "endplate"
        ):
            vertebra = str(row.get("vertebra") or "")
            surface = str(row.get("endplate_surface") or "")
            if vertebra not in _VERTEBRAE or surface not in {
                "superior", "inferior", "both",
            }:
                warnings.append(f"atomic_verification_endplate_identity_missing:{expected_card}")
                row["status"] = "INDETERMINATE"
                row["refined_finding"] = None
                status = "INDETERMINATE"
        if status in {"REJECTED", "INDETERMINATE"}:
            row["refined_finding"] = None
        elif not str(row.get("refined_finding") or "").strip():
            warnings.append(f"atomic_verification_finding_missing:{expected_card}")
            row["status"] = "INDETERMINATE"
            row["refined_finding"] = None
        accepted.append(row)
        decided.add(str(candidate))

    for attention_id in expected_attention:
        if attention_id in decided:
            continue
        warnings.append(f"atomic_verification_candidate_omitted:{expected_card}:{attention_id}")
        accepted.append({
            "candidate": attention_id,
            "card_id": expected_card,
            "structure_group": expected_group,
            "level": expected_level,
            "status": "INDETERMINATE",
            "refined_finding": None,
            "reason": "The card-bound diagnostic response omitted this screening attention.",
        })

    normalized = dict(structured)
    normalized.update({
        "schema_version": ATOMIC_DIAGNOSIS_SCHEMA_VERSION,
        "card_id": expected_card,
        "subject_level": expected_level,
        "structure_group": expected_group,
        "verifications": accepted,
    })
    result = dict(outcome)
    result["structured"] = normalized
    return result, list(dict.fromkeys(warnings))


def _level_map_text(screening_text: str) -> str:
    return _format_level_map(parse_level_map(screening_text))


def merge_verification_outcomes(
    outcomes: Iterable[dict[str, Any]], screening_text: str,
) -> dict[str, Any]:
    verifications: list[dict[str, Any]] = []
    limitations: list[str] = []
    not_assessable: list[str] = []
    for outcome in outcomes:
        structured = outcome.get("structured") if isinstance(outcome, dict) else None
        if not isinstance(structured, dict):
            continue
        rows = structured.get("verifications")
        if isinstance(rows, list):
            verifications.extend(dict(row) for row in rows if isinstance(row, dict))
        for key, target in (("limitations", limitations), ("not_assessable", not_assessable)):
            values = structured.get(key)
            if isinstance(values, list):
                target.extend(str(value).strip() for value in values if str(value).strip())

    level_order = ("T12-L1", "L1-L2", "L2-L3", "L3-L4", "L4-L5", "L5-S1", "unclear")
    by_level: dict[str, list[str]] = {}
    for row in verifications:
        if row.get("status") not in {"CONFIRMED", "REFINED", "ADDED"}:
            continue
        finding = str(row.get("refined_finding") or "").strip()
        if not finding:
            continue
        level = str(row.get("level") or "unclear")
        by_level.setdefault(level, []).append(finding.rstrip("."))

    findings = []
    for level in level_order:
        values = list(dict.fromkeys(by_level.get(level, ())))
        if values:
            findings.append(f"  {level}: " + "; ".join(values) + ".")
    for level in sorted(set(by_level) - set(level_order)):
        values = list(dict.fromkeys(by_level[level]))
        findings.append(f"  {level}: " + "; ".join(values) + ".")

    report_parts = [
        _level_map_text(screening_text),
        "\nPATHOLOGICAL FINDINGS\n" + ("\n".join(findings) if findings else "  None confirmed."),
    ]
    limitations = list(dict.fromkeys(limitations))
    not_assessable = list(dict.fromkeys(not_assessable))
    if limitations:
        report_parts.append("\nTECHNIQUE / PROTOCOL LIMITATIONS\n" + "\n".join(
            f"  {value}" for value in limitations
        ))
    if not_assessable:
        report_parts.append("\nNOT ASSESSABLE\n" + "\n".join(
            f"  {value}" for value in not_assessable
        ))
    audit = {
        "schema_version": ATOMIC_DIAGNOSIS_SCHEMA_VERSION,
        "atomic_pipeline_version": ATOMIC_PIPELINE_VERSION,
        "verifications": verifications,
        "limitations": limitations,
        "not_assessable": not_assessable,
    }
    return {"audit": audit, "report": "\n".join(report_parts)}


def safe_artifact_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "_", str(value or "").lower()).strip("_") or "stage"


def aggregate_request_record(document: dict[str, Any], kind: str) -> dict[str, Any]:
    """Replace unsent monolithic content with an explicit local-merge record."""
    result = dict(document)
    result["prompt"] = {
        "id": f"lumbar_atomic_{safe_artifact_key(kind)}_aggregate",
        "name": f"atomic_{safe_artifact_key(kind)}_aggregate",
        "version": ATOMIC_PIPELINE_VERSION,
        "label": "Local atomic merge record",
        "text": "No aggregate prompt was sent. See .atomic_analysis for exact subrequests.",
    }
    result["sent"] = {
        "header": "LOCAL AGGREGATE ONLY - NOT SENT TO A MODEL",
        "context": "",
        "image_count": 0,
        "images": [],
    }
    return result
