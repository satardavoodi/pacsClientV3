"""Canonical task-specific card templates for Eagle Eye MRI pipelines.

This module is intentionally data-only. It contains no Qt, VTK, DICOM decode,
or model-transport dependency, so modality adapters can consume one immutable
registry without making the shared contract depend on a viewer or body part.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal


CardFamily = Literal["screening", "diagnosis"]


class CardTemplateNotFound(LookupError):
    """No exact card template exists for the requested task and anatomy."""


@dataclass(frozen=True)
class CardTemplate:
    """One immutable Task + Anatomy + Geometry + Sequence card contract."""

    template_id: str
    modality: str
    body_part: str
    family: CardFamily
    key: str
    display_name: str
    decision_question: str
    objective: str
    anatomical_targets: tuple[str, ...]
    required_sequences: tuple[str, ...]
    geometry_roles: tuple[str, ...]
    sagittal_positions: tuple[str, ...]
    axial_positions: tuple[str, ...]
    output_fields: tuple[str, ...]
    model_instructions: str
    sagittal_tile_size: tuple[int, int]
    sagittal_columns: int
    axial_tile_size: tuple[int, int] | None
    layout_strategy: str


_SCREENING_QUESTION = "Is this anatomical target normal or abnormal?"
_DIAGNOSIS_QUESTION = "What exactly is this abnormality?"
_SCREENING_OUTPUT = (
    "anatomical_target",
    "structure",
    "level",
    "laterality",
    "assessment",
    "confidence",
    "visual_salience",
    "slice_persistence",
    "evidence_locations",
)
_DIAGNOSIS_OUTPUT = (
    "anatomical_target",
    "structure",
    "level",
    "diagnosis",
    "morphology",
    "signal_abnormality",
    "laterality",
    "anatomical_effect",
    "severity",
    "evidence_locations",
)
_SCREENING_AXIAL = ("disc_level", "subarticular", "infrapedicular")
_DIAGNOSTIC_AXIAL = (
    "disc_level",
    "max_abnormality",
    "caudal_extent",
)


def _template(
    family: CardFamily,
    key: str,
    display_name: str,
    objective: str,
    anatomical_targets: tuple[str, ...],
    required_sequences: tuple[str, ...],
    sagittal_positions: tuple[str, ...],
    axial_positions: tuple[str, ...],
    model_instructions: str,
    *,
    sagittal_tile_size: tuple[int, int],
    sagittal_columns: int,
    axial_tile_size: tuple[int, int] | None,
    layout_strategy: str = "task-specific-grid-v1",
) -> CardTemplate:
    geometry_roles = tuple(
        dict.fromkeys((*sagittal_positions, *axial_positions))
    )
    return CardTemplate(
        template_id=f"mri.lumbar_spine.{family}.{key}",
        modality="mri",
        body_part="lumbar_spine",
        family=family,
        key=key,
        display_name=display_name,
        decision_question=(
            _SCREENING_QUESTION if family == "screening" else _DIAGNOSIS_QUESTION
        ),
        objective=objective,
        anatomical_targets=anatomical_targets,
        required_sequences=required_sequences,
        geometry_roles=geometry_roles,
        sagittal_positions=sagittal_positions,
        axial_positions=axial_positions,
        output_fields=_SCREENING_OUTPUT if family == "screening" else _DIAGNOSIS_OUTPUT,
        model_instructions=model_instructions,
        sagittal_tile_size=sagittal_tile_size,
        sagittal_columns=sagittal_columns,
        axial_tile_size=axial_tile_size,
        layout_strategy=layout_strategy,
    )


_LUMBAR_SCREENING_TEMPLATES = (
    _template(
        "screening",
        "disc",
        "Lumbar Disc Screening Card",
        "Determine whether each bound lumbar disc is normal or abnormal.",
        ("disc",),
        ("sagittal_t2", "axial_t2"),
        ("right_paracentral", "midline", "left_paracentral"),
        _SCREENING_AXIAL,
        "Detect abnormal disc signal or contour without naming morphology, zone, or diagnosis.",
        sagittal_tile_size=(280, 486),
        sagittal_columns=3,
        axial_tile_size=(200, 200),
        layout_strategy="central-sagittal-separated-axial-groups-v1",
    ),
    _template(
        "screening",
        "canal_neural",
        "Lumbar Canal and Neural Screening Card",
        (
            "Determine whether the central canal, lateral recesses, or bound "
            "neural structures are normal or abnormal."
        ),
        (
            "central_canal",
            "lateral_recess",
            "nerve_root",
            "conus",
            "cauda_equina",
            "epidural_space",
        ),
        ("sagittal_t2", "axial_t2"),
        ("right_paracentral", "midline", "left_paracentral"),
        _SCREENING_AXIAL,
        (
            "Detect abnormal canal or neural appearance without naming stenosis, grade, or neural effect. "
            "Assess central canal caliber independently from disc contour, lateral recess, foramen, and "
            "root findings; use optional MR myelography only as a non-localizing caliber overview."
        ),
        sagittal_tile_size=(280, 486),
        sagittal_columns=3,
        axial_tile_size=(200, 200),
        layout_strategy="central-sagittal-separated-axial-groups-v1",
    ),
    _template(
        "screening",
        "foraminal",
        "Lumbar Neural Foramen Screening Card",
        "Determine whether either bound neural foramen is normal or abnormal.",
        ("neural_foramen",),
        ("sagittal_t2", "sagittal_t1", "axial_t2"),
        (
            "right_foraminal",
            "right_paracentral",
            "left_paracentral",
            "left_foraminal",
        ),
        _SCREENING_AXIAL,
        "Detect abnormal foraminal appearance without grading or attributing its cause.",
        sagittal_tile_size=(240, 416),
        sagittal_columns=4,
        axial_tile_size=(165, 165),
        layout_strategy="bilateral-lateral-sagittal-separated-axial-groups-v1",
    ),
    _template(
        "screening",
        "endplate_marrow",
        "Lumbar Bone Marrow and Endplate Screening Card",
        "Determine whether vertebral marrow, vertebral bodies, or endplates are normal or abnormal.",
        ("endplate", "bone_marrow", "vertebral_body"),
        ("sagittal_t2", "sagittal_t1"),
        ("right_paracentral", "midline", "left_paracentral"),
        (),
        "Detect abnormal signal or morphology without assigning Modic type or another diagnosis.",
        sagittal_tile_size=(300, 520),
        sagittal_columns=3,
        axial_tile_size=None,
        layout_strategy="paired-sagittal-grid-v1",
    ),
    _template(
        "screening",
        "posterior_elements",
        "Lumbar Facet and Posterior Element Screening Card",
        (
            "Determine whether facets, ligamentum flavum, posterior elements, "
            "alignment, or paraspinal tissues are normal or abnormal."
        ),
        (
            "posterior_element",
            "facet_joint",
            "ligamentum_flavum",
            "paraspinal_soft_tissue",
            "alignment",
            "other",
        ),
        ("sagittal_t2", "sagittal_t1", "axial_t2"),
        ("right_paracentral", "left_paracentral"),
        _SCREENING_AXIAL,
        (
            "Detect abnormal posterior-element appearance without classifying "
            "degeneration, hypertrophy, or another cause."
        ),
        sagittal_tile_size=(280, 486),
        sagittal_columns=2,
        axial_tile_size=(190, 190),
        layout_strategy="lateral-central-lateral-separated-axial-groups-v1",
    ),
)


_LUMBAR_DIAGNOSIS_TEMPLATES = (
    _template(
        "diagnosis",
        "disc",
        "Lumbar Disc Diagnosis Card",
        "Classify a screening-positive disc abnormality from multiplanar morphology and signal.",
        ("disc",),
        ("sagittal_t2", "axial_t2"),
        ("right_paracentral", "midline", "left_paracentral"),
        _DIAGNOSTIC_AXIAL,
        (
            "Classify disc contour and displacement morphology. Compare the width of the connection at the "
            "disc margin (base) with every dimension of displaced material (dome) in the same plane. If an "
            "extrusion criterion is met in any plane, classify the disc as extrusion. Report migration "
            "separately. Do not treat morphology as a severity ladder. Preserved bright central T2 nucleus "
            "is negative evidence against desiccation unless the directly visible disc signal proves "
            "otherwise. This card classifies the disc only; canal, recess, and nerve-root abnormalities "
            "belong to their own independently screened canal/neural card."
        ),
        sagittal_tile_size=(384, 256),
        sagittal_columns=3,
        axial_tile_size=(384, 384),
    ),
    _template(
        "diagnosis",
        "canal_neural",
        "Lumbar Canal and Nerve Root Diagnosis Card",
        "Classify a screening-positive canal, lateral-recess, or neural abnormality.",
        (
            "central_canal",
            "lateral_recess",
            "nerve_root",
            "conus",
            "cauda_equina",
            "epidural_space",
        ),
        ("sagittal_t2", "sagittal_t1", "axial_t2"),
        ("right_paracentral", "midline", "left_paracentral"),
        _DIAGNOSTIC_AXIAL,
        (
            "Classify central canal, lateral recess, traversing-root, conus, "
            "cauda-equina, and epidural-space findings. Grade the visible space "
            "independently from root contact, deviation, and compression. "
            "Side must come from patient orientation, not screen position."
        ),
        sagittal_tile_size=(384, 256),
        sagittal_columns=3,
        axial_tile_size=(384, 384),
    ),
    _template(
        "diagnosis",
        "foraminal",
        "Lumbar Neural Foramen Diagnosis Card",
        "Classify a screening-positive neural-foramen abnormality on each side independently.",
        ("neural_foramen",),
        ("sagittal_t2", "sagittal_t1", "axial_t2"),
        ("right_foraminal", "left_foraminal"),
        _DIAGNOSTIC_AXIAL,
        (
            "Classify each neural foramen using perineural fat preservation, "
            "exiting-root contour, and matched sagittal T1/T2 evidence. Use axial "
            "evidence for correlation rather than inventing a sagittal grade."
        ),
        sagittal_tile_size=(384, 256),
        sagittal_columns=2,
        axial_tile_size=(384, 384),
    ),
    _template(
        "diagnosis",
        "endplate_marrow",
        "Lumbar Bone Marrow and Endplate Diagnosis Card",
        (
            "Classify a screening-positive marrow, vertebral-body, or endplate "
            "abnormality from matched signal and morphology."
        ),
        ("endplate", "bone_marrow", "vertebral_body"),
        ("sagittal_t2", "sagittal_t1", "axial_t2"),
        ("right_paracentral", "midline", "left_paracentral"),
        ("max_abnormality",),
        (
            "Classify endplate, marrow, and vertebral-body abnormalities from "
            "matched T1/T2 signal and morphology. Name the exact vertebra and "
            "superior or inferior endplate surface before classifying it. Separate "
            "degenerative endplate change, focal defect or Schmorl node, fracture, "
            "infection, and marrow-replacing lesion when supported; otherwise "
            "return indeterminate. Modic type II requires a reproducible matched "
            "T1/T2 fatty-marrow pattern at that exact surface. Do not duplicate one "
            "vertebral focus under both neighboring disc levels."
        ),
        sagittal_tile_size=(384, 256),
        sagittal_columns=3,
        axial_tile_size=(384, 384),
    ),
    _template(
        "diagnosis",
        "posterior_elements",
        "Lumbar Facet and Posterior Element Diagnosis Card",
        (
            "Classify a screening-positive facet, ligament, posterior-element, "
            "alignment, or paraspinal abnormality."
        ),
        (
            "posterior_element",
            "facet_joint",
            "ligamentum_flavum",
            "paraspinal_soft_tissue",
            "alignment",
            "other",
        ),
        ("sagittal_t2", "sagittal_t1", "axial_t2"),
        ("right_paracentral", "left_paracentral"),
        _DIAGNOSTIC_AXIAL,
        (
            "Classify facet joints, ligamentum flavum, posterior elements, "
            "alignment, and paraspinal soft tissues. Separate facet hypertrophy, "
            "effusion, synovial cyst, ligament thickening, osseous lesion, and "
            "alignment abnormality only when directly supported. Normal posterior "
            "structures remain normal even when an adjacent disc is abnormal. Call "
            "ligamentum flavum thickening only when it is reproducible on at least "
            "two adjacent axial slices and has objective thickness or a directly "
            "visible canal/recess effect. Distinguish true thickening from buckling "
            "or partial-volume appearance; "
            "reject isolated mild prominence without objective effect."
        ),
        sagittal_tile_size=(384, 256),
        sagittal_columns=2,
        axial_tile_size=(384, 384),
    ),
)


_TEMPLATES = (*_LUMBAR_SCREENING_TEMPLATES, *_LUMBAR_DIAGNOSIS_TEMPLATES)
_REGISTRY = {
    (template.modality, template.body_part, template.family, template.key): template
    for template in _TEMPLATES
}
if len(_REGISTRY) != len(_TEMPLATES):
    raise RuntimeError("Eagle Eye card template identities must be unique.")
for _item in _TEMPLATES:
    if not all((
        _item.template_id,
        _item.display_name,
        _item.objective,
        _item.anatomical_targets,
        _item.required_sequences,
        _item.geometry_roles,
        _item.output_fields,
    )):
        raise RuntimeError(f"Incomplete Eagle Eye card template: {_item.template_id}")

CARD_TEMPLATE_REGISTRY = MappingProxyType(_REGISTRY)


def get_card_template(
    modality: str,
    body_part: str,
    family: CardFamily,
    key: str,
) -> CardTemplate:
    """Return one exact template; never substitute another task or anatomy."""
    identity = (
        str(modality).strip().casefold(),
        str(body_part).strip().casefold(),
        str(family).strip().casefold(),
        str(key).strip().casefold(),
    )
    try:
        return CARD_TEMPLATE_REGISTRY[identity]
    except KeyError as exc:
        raise CardTemplateNotFound("No Eagle Eye card template exists for " + ".".join(identity)) from exc


def list_card_templates(
    *,
    modality: str | None = None,
    body_part: str | None = None,
    family: CardFamily | None = None,
) -> tuple[CardTemplate, ...]:
    """List registered templates in deterministic clinical display order."""
    filters = {
        "modality": str(modality).strip().casefold() if modality is not None else None,
        "body_part": str(body_part).strip().casefold() if body_part is not None else None,
        "family": str(family).strip().casefold() if family is not None else None,
    }
    return tuple(
        template
        for template in _TEMPLATES
        if all(
            expected is None or getattr(template, field) == expected
            for field, expected in filters.items()
        )
    )
