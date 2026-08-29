"""Versioned qualitative lumbar stenosis grading contracts.

The model must not invent the meaning of ``mild``, ``moderate`` and ``severe``
on every run.  This module is the single, framework-free authority for the
three stenosis systems used by Eagle Eye.  Prompts render this catalog; later
evidence selectors and deterministic report rendering can consume the same
objects without copying clinical criteria into transport or UI code.

Measurements are deliberately absent.  Dural-sac area and linear dimensions
may become supporting evidence, but the qualitative morphology remains the
grading authority and a model must never infer a grade from a number alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


GRADING_CATALOG_VERSION = "1.0.0"


@dataclass(frozen=True)
class GradeDefinition:
    """One ordinal grade in a named qualitative grading system."""

    value: int
    severity: str
    criteria: str


@dataclass(frozen=True)
class GradingSystem:
    """A complete, ordered grading contract for one anatomical target."""

    id: str
    target: str
    primary_sequence: str
    grades: Tuple[GradeDefinition, ...]

    def __post_init__(self) -> None:
        values = tuple(grade.value for grade in self.grades)
        if values != tuple(range(len(self.grades))):
            raise ValueError(f"{self.id} grades must be contiguous and start at zero")


CENTRAL_CANAL = GradingSystem(
    id="lee_central_canal",
    target="central_canal_stenosis",
    primary_sequence="axial_t2",
    grades=(
        GradeDefinition(
            0,
            "none",
            "The anterior CSF space is not obliterated.",
        ),
        GradeDefinition(
            1,
            "mild",
            "The anterior CSF space is mildly obliterated, but all cauda "
            "equina rootlets remain visually separated.",
        ),
        GradeDefinition(
            2,
            "moderate",
            "The anterior CSF space is moderately obliterated and some cauda "
            "equina rootlets are aggregated, so they cannot all be visually "
            "separated.",
        ),
        GradeDefinition(
            3,
            "severe",
            "The dural sac is markedly compressed and no cauda equina "
            "rootlets can be visually separated; they appear as a single bundle.",
        ),
    ),
)


NEURAL_FORAMEN = GradingSystem(
    id="lee_neural_foramen",
    target="neural_foraminal_stenosis",
    primary_sequence="sagittal_t1",
    grades=(
        GradeDefinition(
            0,
            "none",
            "Perineural foraminal fat is preserved without stenosis.",
        ),
        GradeDefinition(
            1,
            "mild",
            "Perineural fat is obliterated in two opposing directions, "
            "without morphological change of the nerve root.",
        ),
        GradeDefinition(
            2,
            "moderate",
            "Perineural fat is obliterated in four directions, without "
            "morphological change of the nerve root.",
        ),
        GradeDefinition(
            3,
            "severe",
            "The nerve root shows collapse or another definite morphological change.",
        ),
    ),
)


LATERAL_RECESS = GradingSystem(
    id="bartynski_lateral_recess",
    target="lateral_recess_stenosis",
    primary_sequence="axial_t2",
    grades=(
        GradeDefinition(
            0,
            "none",
            "The lateral recess is normal and the traversing nerve root is free.",
        ),
        GradeDefinition(
            1,
            "mild",
            "The lateral recess is narrowed or contacts the traversing nerve "
            "root without nerve-root deviation.",
        ),
        GradeDefinition(
            2,
            "moderate",
            "Lateral recess narrowing produces definite nerve-root deviation "
            "without compression.",
        ),
        GradeDefinition(
            3,
            "severe",
            "Lateral recess narrowing produces definite nerve-root compression.",
        ),
    ),
)


LUMBAR_STENOSIS_SYSTEMS = (CENTRAL_CANAL, NEURAL_FORAMEN, LATERAL_RECESS)


def prompt_rubric() -> str:
    """Render the catalog into deterministic English prompt text."""
    lines = [
        "STENOSIS GRADING CONTRACT",
        "",
        f"Catalog version: {GRADING_CATALOG_VERSION}",
        "Use these definitions exactly whenever a stenosis grade is requested.",
        "A grade is valid only when the primary sequence is assessable and the",
        "defining morphology is visible. Otherwise leave the grading fields null.",
        "During verification, use INDETERMINATE status and describe the limitation",
        "under NOT ASSESSABLE in the final report; NOT_ASSESSABLE is not a status.",
        "Do not infer a grade from measurements alone. Measurements may support",
        "the morphological assessment but never replace it.",
    ]
    for system in LUMBAR_STENOSIS_SYSTEMS:
        lines.extend((
            "",
            f"{system.id} ({system.target}; primary sequence: "
            f"{system.primary_sequence})",
        ))
        for grade in system.grades:
            lines.append(
                f"  Grade {grade.value} / {grade.severity}: {grade.criteria}")
    return "\n".join(lines) + "\n"


LUMBAR_STENOSIS_GRADING_PROMPT = prompt_rubric()
