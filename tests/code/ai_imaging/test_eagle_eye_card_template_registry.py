"""Structural guards for the canonical Eagle Eye MRI card registry."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from modules.ai_imaging.eagle_eye import card_templates
from modules.ai_imaging.eagle_eye_lumbar import anatomy_cards, atomic_pipeline


EXPECTED_TEMPLATE_KEYS = (
    "disc",
    "canal_neural",
    "foraminal",
    "endplate_marrow",
    "posterior_elements",
)
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_lumbar_mri_registry_has_two_task_specific_five_card_families():
    screening = card_templates.list_card_templates(
        modality="mri", body_part="lumbar_spine", family="screening"
    )
    diagnosis = card_templates.list_card_templates(
        modality="mri", body_part="lumbar_spine", family="diagnosis"
    )

    assert tuple(template.key for template in screening) == EXPECTED_TEMPLATE_KEYS
    assert tuple(template.key for template in diagnosis) == EXPECTED_TEMPLATE_KEYS
    assert len({template.template_id for template in (*screening, *diagnosis)}) == 10
    assert all(template.anatomical_targets for template in (*screening, *diagnosis))
    assert all(template.required_sequences for template in (*screening, *diagnosis))
    assert all(template.geometry_roles for template in (*screening, *diagnosis))
    assert all("level card" not in template.display_name.lower() for template in (*screening, *diagnosis))


def test_screening_and_diagnosis_contracts_do_not_blur_their_roles():
    screening = card_templates.get_card_template(
        "mri", "lumbar_spine", "screening", "disc"
    )
    diagnosis = card_templates.get_card_template(
        "mri", "lumbar_spine", "diagnosis", "disc"
    )

    assert screening.decision_question == "Is this anatomical target normal or abnormal?"
    assert set(screening.output_fields) >= {
        "assessment",
        "visual_salience",
        "evidence_locations",
    }
    assert "diagnosis" not in screening.output_fields
    assert diagnosis.decision_question == "What exactly is this abnormality?"
    assert set(diagnosis.output_fields) >= {
        "diagnosis",
        "morphology",
        "laterality",
        "severity",
    }

    with pytest.raises(FrozenInstanceError):
        screening.key = "changed"


def test_registry_encodes_task_specific_lumbar_sequence_selection():
    marrow = card_templates.get_card_template(
        "mri", "lumbar_spine", "screening", "endplate_marrow"
    )
    foramen = card_templates.get_card_template(
        "mri", "lumbar_spine", "screening", "foraminal"
    )
    disc = card_templates.get_card_template(
        "mri", "lumbar_spine", "screening", "disc"
    )
    canal = card_templates.get_card_template(
        "mri", "lumbar_spine", "screening", "canal_neural"
    )
    posterior = card_templates.get_card_template(
        "mri", "lumbar_spine", "screening", "posterior_elements"
    )

    assert marrow.required_sequences == ("sagittal_t2", "sagittal_t1")
    assert marrow.axial_positions == ()
    assert set(foramen.required_sequences) == {
        "sagittal_t1",
        "sagittal_t2",
        "axial_t2",
    }
    assert foramen.sagittal_positions == (
        "right_foraminal",
        "right_paracentral",
        "left_paracentral",
        "left_foraminal",
    )
    assert disc.required_sequences == ("sagittal_t2", "axial_t2")
    assert disc.layout_strategy == "central-sagittal-separated-axial-groups-v1"
    assert canal.layout_strategy == "central-sagittal-separated-axial-groups-v1"
    assert foramen.layout_strategy == (
        "bilateral-lateral-sagittal-separated-axial-groups-v1"
    )
    assert posterior.layout_strategy == (
        "lateral-central-lateral-separated-axial-groups-v1"
    )
    assert marrow.layout_strategy == "paired-sagittal-grid-v1"


def test_lumbar_runtime_projects_the_canonical_registry_without_combined_cards():
    assert tuple(request.key for request in atomic_pipeline.SCREENING_REQUESTS) == (
        "disc",
        "canal_neural",
        "foraminal",
        "endplate_marrow",
        "posterior_elements",
    )
    assert set(atomic_pipeline.STRUCTURE_CARD_PROFILES) >= set(EXPECTED_TEMPLATE_KEYS)

    for key in EXPECTED_TEMPLATE_KEYS:
        diagnosis_template = card_templates.get_card_template(
            "mri", "lumbar_spine", "diagnosis", key
        )
        assert atomic_pipeline.STRUCTURE_CARD_PROFILES[key].template_id == (
            diagnosis_template.template_id
        )
        spec = anatomy_cards._card_spec(key)
        template = card_templates.get_card_template(
            "mri", "lumbar_spine", "screening", key
        )
        assert tuple(dict.fromkeys(role for role, _plane in spec["sagittal"])) == tuple(
            role for role in template.required_sequences if role.startswith("sagittal_")
        )
        assert spec["axial"] is bool(template.axial_positions)


def test_registry_rejects_unknown_templates_without_silent_fallback():
    with pytest.raises(card_templates.CardTemplateNotFound):
        card_templates.get_card_template(
            "mri", "lumbar_spine", "screening", "unknown"
        )


def test_canonical_mri_document_owns_the_pipeline_and_marks_snapshots_historical():
    canonical = (REPO_ROOT / "docs/pipelines/eagle-eye-mri.md").read_text(
        encoding="utf-8"
    )
    assert "official primary MRI architecture" in canonical
    assert "1. Geometry Processing" in canonical
    assert "2. Anatomical Localization / Site Recognition" in canonical
    assert "3. Screening Card Generation" in canonical
    assert "4. Diagnostic Card Generation" in canonical
    assert "5. Pathology Diagnosis / Classification" in canonical
    assert "modules/ai_imaging/eagle_eye/card_templates.py" in canonical

    for relative in (
        "docs/plans/EAGLE_EYE_LUMBAR_CURRENT_STATE_2026-09-02.md",
        "docs/plans/EAGLE_EYE_ATOMIC_STRUCTURE_PIPELINE_2026-09-02.md",
    ):
        snapshot = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "historical" in snapshot.lower()
        assert "superseded for architecture" in snapshot.lower()
