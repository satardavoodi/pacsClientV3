"""Regression guards for anatomy-specific atomic lumbar analysis."""

import json
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_lumbar import atomic_pipeline
from modules.ai_imaging.eagle_eye_lumbar import focus_evidence
from modules.ai_imaging.eagle_eye_lumbar import llm_backend
from modules.ai_imaging.eagle_eye_lumbar import screening_attention
from modules.ai_imaging.eagle_eye_lumbar.evidence_request import build_evidence_plan
from modules.ai_imaging.eagle_eye_lumbar.llm_package import AnalysisPackage, PackagedImage


def test_atomic_screening_domains_are_bounded_and_cover_core_structures():
    domains = atomic_pipeline.SCREENING_DOMAINS

    assert [item.key for item in domains] == [
        "disc",
        "canal_neural",
        "foraminal",
        "endplate_marrow",
        "posterior_elements",
    ]
    assert len({structure for item in domains for structure in item.structures}) == sum(
        len(item.structures) for item in domains
    )
    assert atomic_pipeline.structure_group("disc") == "disc"
    assert atomic_pipeline.structure_group("endplate") == "endplate_marrow"
    assert atomic_pipeline.structure_group("lateral_recess") == "canal_neural"
    assert atomic_pipeline.structure_group("neural_foramen") == "foraminal"
    assert atomic_pipeline.structure_group("facet_joint") == "posterior_elements"


def test_atomic_screening_dispatch_is_five_task_specific_low_variance_requests():
    requests = atomic_pipeline.SCREENING_REQUESTS

    assert [item.key for item in requests] == [
        "disc",
        "canal_neural",
        "foraminal",
        "endplate_marrow",
        "posterior_elements",
    ]
    assert requests[0].structures == ("disc",)
    assert set(requests[1].structures) >= {"central_canal", "nerve_root"}
    assert requests[2].structures == ("neural_foramen",)
    assert set(requests[3].structures) == {
        "endplate", "bone_marrow", "vertebral_body",
    }
    assert set(requests[4].structures) >= {
        "facet_joint", "ligamentum_flavum",
    }
    assert requests[0].evidence_roles == ("sagittal_t2", "axial_t2")
    assert requests[1].evidence_roles == ("sagittal_t2", "axial_t2")
    assert requests[2].evidence_roles == (
        "sagittal_t2", "sagittal_t1", "axial_t2",
    )
    assert requests[3].evidence_roles == ("sagittal_t2", "sagittal_t1")
    assert requests[4].evidence_roles == (
        "sagittal_t2", "sagittal_t1", "axial_t2",
    )

    stage = atomic_pipeline.screening_stage_for(
        SimpleNamespace(
            model_feature="eagle_eye_screening",
            model_default="gemini-3.1-pro-preview",
            temperature=1.0,
        ),
        requests[0],
    )

    assert stage.name == "screening_disc"
    assert stage.temperature == 1.0
    # Gemini reasoning tokens share this allowance with the visible JSON. The
    # smaller historical ceiling truncated before the findings array began.
    assert stage.max_output_tokens == 24000
    assert "Return exactly one compact JSON object and no prose" in stage.text
    assert "LEVEL MAP\n  <level>" not in stage.text
    assert '"level_map"' not in stage.text
    assert "sole anatomical-map authority" in stage.text


def test_atomic_screening_prompt_forbids_diagnosis_and_limits_anatomy():
    stage = atomic_pipeline.screening_stage_for(
        SimpleNamespace(
            model_feature="eagle_eye_screening",
            model_default="gemini-3.1-pro-preview",
            temperature=1.0,
        ),
        atomic_pipeline.SCREENING_REQUESTS[0],
    )

    assert stage.name == "screening_disc"
    assert "anatomy-only card" in stage.text
    assert "structures: disc." in stage.text
    assert "Do not diagnose" in stage.text
    assert "protrusion" not in stage.text.lower()
    assert stage.max_output_tokens == 24000


def test_disc_screening_is_presence_level_magnitude_and_evidence_only():
    stage = atomic_pipeline.screening_stage_for(
        SimpleNamespace(
            model_feature="eagle_eye_screening",
            model_default="gemini-3.1-pro-preview",
            temperature=1.0,
        ),
        atomic_pipeline.SCREENING_REQUESTS[0],
    )

    assert "STRUCTURE-BY-STRUCTURE ABNORMALITY SWEEP" in stage.text
    assert "abnormality magnitude" in stage.text
    assert "Inspect every allowed structure independently" in stage.text
    assert "For `disc`" in stage.text
    assert "laterality=not_applicable" in stage.text
    assert '"visual_salience"' in stage.text
    assert '"locations"' in stage.text
    assert '"observable_features"' not in stage.text
    assert '"companion_review"' not in stage.text
    assert "space_effacement" not in stage.text
    assert "visible_neural_relationship" not in stage.text


def test_disc_screening_contract_rejects_diagnostic_attributes():
    request = atomic_pipeline.SCREENING_REQUESTS[0]
    neutral = {
        "schema_version": atomic_pipeline.ATOMIC_SCREENING_SCHEMA_VERSION,
        "screening_request": request.key,
        "findings": [{
            "structure": "disc",
            "assessment": "abnormal",
            "level": "L5-S1",
            "vertebra": None,
            "endplate_surface": "not_applicable",
            "laterality": "not_applicable",
            "confidence": "high",
            "visual_salience": "marked",
            "within_study_priority": "dominant",
            "slice_persistence": "three_or_more_adjacent_slices",
            "locations": [],
        }],
    }

    assert atomic_pipeline.screening_outcome_errors(
        request, {"structured": neutral},
    ) == []

    diagnostic = json.loads(json.dumps(neutral))
    diagnostic["findings"][0]["laterality"] = "central"
    diagnostic["findings"][0]["observable_features"] = {
        "space_effacement": "marked",
    }
    diagnostic["findings"][0]["companion_review"] = {
        "right_traversing_nerve_root": "compression",
    }
    errors = atomic_pipeline.screening_outcome_errors(
        request, {"structured": diagnostic},
    )

    assert "finding_1_laterality" in errors
    assert "finding_1_forbidden_diagnostic_field_observable_features" in errors
    assert "finding_1_forbidden_diagnostic_field_companion_review" in errors


def test_endplate_screening_requires_vertebral_surface_identity():
    request = atomic_pipeline.SCREENING_REQUESTS[3]
    stage = atomic_pipeline.screening_stage_for(
        SimpleNamespace(
            model_feature="eagle_eye_screening",
            model_default="gemini-3.1-pro-preview",
            temperature=1.0,
        ),
        request,
    )

    assert '"endplate_surface"' in stage.text
    assert "vertebral anchor" in stage.text
    errors = atomic_pipeline.screening_outcome_errors(request, {
        "structured": {
            "schema_version": atomic_pipeline.ATOMIC_SCREENING_SCHEMA_VERSION,
            "screening_request": request.key,
            "findings": [{
                "structure": "endplate",
                "assessment": "abnormal",
                "level": "L4-L5",
                "vertebra": None,
                "endplate_surface": "not_applicable",
            }],
        }
    })

    assert "finding_1_vertebra" in errors
    assert "finding_1_endplate_surface" in errors


def test_atomic_screening_contract_rejects_a_parseable_but_wrong_gate_response():
    request = atomic_pipeline.SCREENING_REQUESTS[0]

    assert atomic_pipeline.screening_outcome_errors(request, {
        "structured": {
            "schema_version": atomic_pipeline.ATOMIC_SCREENING_SCHEMA_VERSION,
            "screening_request": request.key,
            "findings": [],
        }
    }) == []

    errors = atomic_pipeline.screening_outcome_errors(request, {
        "structured": {
            "schema_version": "2.8.0",
            "screening_request": "endplate_marrow",
            "findings": [{
                "structure": "facet_joint",
                "assessment": "normal",
            }],
        }
    })

    assert errors == [
        "schema_version",
        "screening_request",
        "finding_1_structure",
        "finding_1_assessment",
    ]


def test_atomic_merge_keeps_domain_provenance_and_one_shared_contract():
    outcomes = [
        (
            atomic_pipeline.SCREENING_REQUESTS[0],
            {
                "answer": "",
                "structured": {
                    "schema_version": atomic_pipeline.ATOMIC_SCREENING_SCHEMA_VERSION,
                    "level_map": [{"level": "L5-S1", "axial_frames": [21, 25]}],
                    "findings": [{
                        "structure": "disc",
                        "assessment": "abnormal",
                        "level": "L5-S1",
                        "locations": [],
                    }],
                },
            },
        ),
        (
            atomic_pipeline.SCREENING_REQUESTS[4],
            {
                "answer": "",
                "structured": {
                    "schema_version": atomic_pipeline.ATOMIC_SCREENING_SCHEMA_VERSION,
                    "level_map": [{"level": "L5-S1", "axial_frames": [21, 25]}],
                    "findings": [{
                        "structure": "facet_joint",
                        "assessment": "abnormal",
                        "level": "L5-S1",
                        "locations": [],
                    }],
                },
            },
        ),
    ]

    merged = atomic_pipeline.merge_screening_outcomes(outcomes)

    assert merged["structured"]["schema_version"] == "3.4.0"
    assert [row["screening_domain"] for row in merged["structured"]["findings"]] == [
        "disc",
        "posterior_elements",
    ]
    assert merged["structured"]["level_map"] == [
        {"level": "L5-S1", "axial_frames": [21, 25]}
    ]
    assert "L5-S1: axial frames 21-25" in merged["answer"]


def test_atomic_stage_rejects_a_truncated_unstructured_response(tmp_path):
    image_path = tmp_path / "atlas.png"
    image_path.write_bytes(b"synthetic")
    package = AnalysisPackage(
        tmp_path,
        "session",
        "lumbar_mri",
        SimpleNamespace(as_dict=lambda: {}),
        "header",
        [PackagedImage(image_path, "atlas", "screening-sagittal_t2", 1)],
    )
    stage = atomic_pipeline.screening_stage_for(
        SimpleNamespace(
            model_feature="eagle_eye_screening",
            model_default="gemini-3.1-pro-preview",
            temperature=1.0,
        ),
        atomic_pipeline.SCREENING_REQUESTS[0],
    )

    with pytest.raises(llm_backend._StageExecutionError, match="truncated_response:23996/24000"):
        llm_backend._execute_atomic_stage(
            root=tmp_path,
            number=1,
            total=3,
            artifact_key="screening_disc",
            stage=stage,
            stage_model="gemini-3.1-pro-preview",
            package=package,
            backend="company",
            send=lambda *_args: {
                "content": '{"schema_version":"3.0.0","findings":[',
                "usage": {"completion_tokens": 23996},
            },
            header="header",
        )

    saved = tmp_path / ".atomic_analysis/stage1/screening_disc_structured.json"
    assert saved.is_file()
    assert '"truncated": true' in saved.read_text(encoding="utf-8")


def test_atomic_screening_does_not_require_retired_gemini_card_templates():
    merged = atomic_pipeline.merge_screening_outcomes([(
        atomic_pipeline.SCREENING_REQUESTS[0],
        {
            "answer": "",
            "structured": {
                "schema_version": "3.0.0",
                "level_map": [{"level": "L5-S1", "axial_frames": [21, 25]}],
                "findings": [{
                    "structure": "disc", "assessment": "abnormal",
                    "level": "L5-S1", "laterality": "right",
                    "confidence": "high", "visual_salience": "marked",
                    "within_study_priority": "dominant",
                    "slice_persistence": "three_or_more_adjacent_slices",
                    "observable_features": {}, "locations": [],
                }],
            },
        },
    )])

    normalized = screening_attention.normalize_attention(merged["structured"])

    assert "screening_level_card_template_missing" not in normalized["warnings"]


def test_evidence_plan_splits_one_level_into_structure_specific_cards():
    structured = {
        "schema_version": "2.7.0",
        "findings": [
            {
                "attention_id": "attention-01",
                "structure": "disc",
                "assessment": "abnormal",
                "level": "L5-S1",
                "confidence": "high",
                "visual_salience": "marked",
                "within_study_priority": "dominant",
                "slice_persistence": "three_or_more_adjacent_slices",
                "locations": [],
            },
            {
                "attention_id": "attention-02",
                "structure": "facet_joint",
                "assessment": "abnormal",
                "level": "L5-S1",
                "confidence": "moderate",
                "visual_salience": "definite",
                "within_study_priority": "secondary",
                "slice_persistence": "two_adjacent_slices",
                "locations": [],
            },
        ],
        "level_card_templates": [],
    }

    plan = build_evidence_plan(
        "LEVEL MAP\n  L5-S1: axial frames 21-25",
        structured,
        None,
        max_focuses=8,
    )

    assert [(item.level, item.card_kind) for item in plan.focuses] == [
        ("L5-S1", "structure:disc"),
        ("L5-S1", "structure:posterior_elements"),
    ]
    assert plan.focuses[0].attention_ids == ("attention-01",)
    assert plan.focuses[1].attention_ids == ("attention-02",)


def test_structure_card_profiles_use_only_decision_relevant_planes():
    disc = atomic_pipeline.STRUCTURE_CARD_PROFILES["disc"]
    foramen = atomic_pipeline.STRUCTURE_CARD_PROFILES["foraminal"]
    canal = atomic_pipeline.STRUCTURE_CARD_PROFILES["canal_neural"]

    assert disc.sagittal_sequences == ("sagittal_t2",)
    assert disc.sagittal_planes == (
        "right_paracentral_plane",
        "midline_plane",
        "left_paracentral_plane",
    )
    assert len(disc.axial_planes) == 3
    assert foramen.sagittal_planes == (
        "right_foraminal_plane",
        "left_foraminal_plane",
    )
    assert foramen.sagittal_sequences == ("sagittal_t2", "sagittal_t1")
    assert canal.sagittal_sequences == ("sagittal_t2", "sagittal_t1")


def test_atomic_verification_prompt_is_one_card_one_structure_decision():
    stage = atomic_pipeline.verification_stage_for(
        SimpleNamespace(
            model_feature="eagle_eye",
            model_default="gpt-5.6-sol",
            temperature=0.2,
        ),
        "disc",
    )

    assert stage.name == "verification_disc"
    assert "exactly one structure-specific card" in stage.text
    assert "Do not inspect another level outside the card" in stage.text
    assert "base" in stage.text and "dome" in stage.text
    assert "MANDATORY COMPANION ASSESSMENTS" not in stage.text
    assert "Bartynski" not in stage.text
    assert '"structure": "disc"' in stage.text
    assert "right S1" not in stage.text
    assert stage.temperature == 0.2
    assert stage.max_output_tokens == 12000


def test_posterior_element_verification_requires_objective_flavum_evidence():
    stage = atomic_pipeline.verification_stage_for(
        SimpleNamespace(
            model_feature="eagle_eye",
            model_default="gpt-5.6-sol",
            temperature=0.2,
        ),
        "posterior_elements",
    )

    assert "two adjacent axial slices" in stage.text
    assert "buckling or partial-volume" in stage.text
    assert "REJECTED" in stage.text
    assert "REFINED does not mean" in stage.text
    assert stage.temperature == 0.2


def test_endplate_verification_requires_exact_anchor_and_paired_signal():
    stage = atomic_pipeline.verification_stage_for(
        SimpleNamespace(
            model_feature="eagle_eye",
            model_default="gpt-5.6-sol",
            temperature=0.2,
        ),
        "endplate_marrow",
    )

    assert "exact vertebra" in stage.text
    assert "superior or inferior endplate surface" in stage.text
    assert "matched T1/T2" in stage.text
    assert "Do not duplicate one vertebral focus" in stage.text
    assert '"vertebra"' in stage.text
    assert '"endplate_surface"' in stage.text


def test_disc_card_metadata_contains_only_neutral_screening_handoff(tmp_path):
    requirements = focus_evidence._required_companion_assessments("disc")
    assert requirements == []
    focus = SimpleNamespace(structure_attention=(SimpleNamespace(
        attention_id="attention-01",
        structure="disc",
        assessment="abnormal",
        vertebra=None,
        endplate_surface="not_applicable",
        laterality="central",
        confidence="high",
        visual_salience="marked",
        within_study_priority="dominant",
        slice_persistence="three_or_more_adjacent_slices",
        observable_features=(("space_effacement", "marked"),),
    ),))
    public = focus_evidence._structure_metadata(focus)
    assert public == [{
        "attention_id": "attention-01",
        "structure": "disc",
        "assessment": "abnormal",
        "vertebra": None,
        "endplate_surface": "not_applicable",
        "confidence": "high",
        "abnormality_magnitude": "marked",
        "slice_persistence": "three_or_more_adjacent_slices",
    }]
    image = PackagedImage(
        tmp_path / "card.png", "", "focus-01", 1,
        card_payload={
            "card_metadata": {
                "card_id": "focus-01",
                "subject_level": "L5-S1",
                "structure_group": "disc",
                "attention_ids": ["attention-01"],
            }
        },
    )
    package = AnalysisPackage(
        tmp_path, "session", "lumbar", SimpleNamespace(as_dict=lambda: {}),
        "header", [image],
    )
    outcome = {
        "structured": {
            "card_id": "focus-01",
            "subject_level": "L5-S1",
            "structure_group": "disc",
            "verifications": [{
                "candidate": "attention-01",
                "card_id": "focus-01",
                "structure_group": "disc",
                "level": "L5-S1",
                "structure": "disc",
                "status": "CONFIRMED",
                "refined_finding": "Disc abnormality.",
            }],
        }
    }

    normalized, warnings = atomic_pipeline.validate_verification_outcome(
        package, 1, outcome,
    )

    assert warnings == []
    companions = [
        row for row in normalized["structured"]["verifications"]
        if row.get("candidate") is None
    ]
    assert companions == []

    diagnostic_label = json.loads(json.dumps(outcome))
    diagnostic_label["structured"]["verifications"][0]["structure"] = (
        "right paracentral disc extrusion"
    )
    rejected, warnings = atomic_pipeline.validate_verification_outcome(
        package, 1, diagnostic_label,
    )
    assert "atomic_verification_structure_invalid:focus-01" in warnings
    assert rejected["structured"]["verifications"][0]["status"] == "INDETERMINATE"


def test_atomic_report_merge_preserves_card_identity_and_level_map():
    outcomes = [
        {
            "structured": {
                "verifications": [{
                    "candidate": "attention-01",
                    "card_id": "focus-01",
                    "structure_group": "disc",
                    "level": "L5-S1",
                    "status": "REFINED",
                    "refined_finding": "Right central disc extrusion with caudal migration.",
                    "reason": "Sagittal and axial morphology agree.",
                }],
                "limitations": [],
            }
        }
    ]

    merged = atomic_pipeline.merge_verification_outcomes(
        outcomes,
        "LEVEL MAP\n  L5-S1: axial frames 21-25",
    )

    assert merged["audit"]["verifications"][0]["card_id"] == "focus-01"
    assert "L5-S1: axial frames 21-25" in merged["report"]
    assert "L5-S1: Right central disc extrusion" in merged["report"]


def test_atomic_screening_package_renumbers_filtered_atlas_pages(tmp_path):
    images = [
        PackagedImage(tmp_path / f"page-{index}.png", "", session, index)
        for index, session in enumerate(
            ("screening-sagittal_t2", "screening-sagittal_t1", "screening-axial_t2"),
            start=1,
        )
    ]
    package = AnalysisPackage(
        tmp_path, "session", "lumbar", SimpleNamespace(as_dict=lambda: {}),
        "header", images,
        evidence_audit={
            "coordinate_space": "tile_content_0_1000",
            "pages": [
                {
                    "image_index": index,
                    "role": role,
                    "tiles": [{"tile_id": f"tile-{index}", "image_index": index}],
                }
                for index, role in enumerate(
                    ("sagittal_t2", "sagittal_t1", "axial_t2"), start=1
                )
            ],
        },
    )

    disc = atomic_pipeline.screening_package_for(
        package, atomic_pipeline.SCREENING_REQUESTS[0],
    )
    canal = atomic_pipeline.screening_package_for(
        package, atomic_pipeline.SCREENING_REQUESTS[1],
    )
    foraminal = atomic_pipeline.screening_package_for(
        package, atomic_pipeline.SCREENING_REQUESTS[2],
    )
    marrow = atomic_pipeline.screening_package_for(
        package, atomic_pipeline.SCREENING_REQUESTS[3],
    )
    posterior = atomic_pipeline.screening_package_for(
        package, atomic_pipeline.SCREENING_REQUESTS[4],
    )

    assert [image.session for image in disc.images] == [
        "screening-sagittal_t2", "screening-axial_t2",
    ]
    assert [image.session for image in canal.images] == [
        "screening-sagittal_t2", "screening-axial_t2",
    ]
    assert [image.session for image in marrow.images] == [
        "screening-sagittal_t2", "screening-sagittal_t1",
    ]
    assert [image.session for image in foraminal.images] == [
        "screening-sagittal_t2", "screening-sagittal_t1", "screening-axial_t2",
    ]
    assert [image.session for image in posterior.images] == [
        "screening-sagittal_t2", "screening-sagittal_t1", "screening-axial_t2",
    ]
    assert [image.index for image in disc.images] == [1, 2]
    assert [page["image_index"] for page in disc.evidence_audit["pages"]] == [1, 2]
    assert [
        page["tiles"][0]["image_index"] for page in disc.evidence_audit["pages"]
    ] == [1, 2]
    assert disc.evidence_audit["atomic_screening_evidence_roles"] == [
        "sagittal_t2", "axial_t2",
    ]


def test_atomic_screening_package_never_falls_back_to_irrelevant_images(tmp_path):
    package = AnalysisPackage(
        tmp_path,
        "session",
        "lumbar",
        SimpleNamespace(as_dict=lambda: {}),
        "header",
        [
            PackagedImage(
                tmp_path / f"page-{index}.png", "", session, index,
            )
            for index, session in enumerate(
                (
                    "screening-sagittal_t2",
                    "screening-sagittal_t1",
                    "screening-axial_t2",
                ),
                start=1,
            )
        ],
        evidence_audit={},
    )

    filtered = atomic_pipeline.screening_package_for(
        package, atomic_pipeline.SCREENING_REQUESTS[3],
    )

    assert [image.session for image in filtered.images] == [
        "screening-sagittal_t2", "screening-sagittal_t1",
    ]


def test_atomic_verification_rejects_cross_card_identity_and_fills_omission(tmp_path):
    image = PackagedImage(
        tmp_path / "card.png", "", "focus-01", 1,
        card_payload={
            "card_metadata": {
                "card_id": "focus-01",
                "subject_level": "L5-S1",
                "structure_group": "disc",
                "attention_ids": ["attention-01"],
            }
        },
    )
    package = AnalysisPackage(
        tmp_path, "session", "lumbar", SimpleNamespace(as_dict=lambda: {}),
        "header", [image],
    )
    outcome = {
        "structured": {
            "verifications": [{
                "candidate": "attention-01",
                "card_id": "focus-99",
                "structure_group": "disc",
                "level": "L4-L5",
                "status": "CONFIRMED",
                "refined_finding": "Wrong-card finding.",
            }]
        }
    }

    normalized, warnings = atomic_pipeline.validate_verification_outcome(
        package, 1, outcome,
    )

    assert "atomic_verification_identity_conflict:focus-01" in warnings
    assert normalized["structured"]["verifications"] == [{
        "candidate": "attention-01",
        "card_id": "focus-01",
        "structure_group": "disc",
        "level": "L5-S1",
        "status": "INDETERMINATE",
        "refined_finding": None,
        "reason": "The card-bound diagnostic response omitted this screening attention.",
    }]
