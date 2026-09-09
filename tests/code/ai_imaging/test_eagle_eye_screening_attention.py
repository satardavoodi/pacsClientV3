"""Synthetic guards for localization-only screening and a diagnosis-free handoff."""

import json
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_lumbar import analysis_prompt, llm_backend
from modules.ai_imaging.eagle_eye_lumbar.evidence_request import build_evidence_plan
from modules.ai_imaging.eagle_eye_lumbar.llm_package import PackagedImage


def test_screening_has_no_diagnostic_rubric_or_label_example():
    text = analysis_prompt.LUMBAR_SCREENING.text
    assert '"structure": "<allowlisted_anatomical_structure>"' in text
    assert '"assessment": "abnormal"' in text
    assert "DISC DISPLACEMENT MORPHOLOGY CONTRACT" not in text
    assert "lee_central_canal" not in text
    assert '"candidate":' not in text
    assert "Try to name the most likely morphology" not in text
    assert "DISC DISPLACEMENT MORPHOLOGY CONTRACT" in analysis_prompt.LUMBAR_VERIFICATION.text


def test_screening_requires_anatomical_location_in_addition_to_pixels():
    text = " ".join(analysis_prompt.LUMBAR_SCREENING.text.split())
    assert "Anatomical location is mandatory; pixel coordinates alone are not a location" in text
    assert "disc, endplate or facet_joint names anatomy, not a diagnosis" in text


def test_diagnostic_workflow_resolves_anatomy_and_correspondence_before_classification():
    text = " ".join(analysis_prompt.LUMBAR_VERIFICATION.text.split())
    workflow = text.split("PATHOLOGY-FOCUS DIFFERENTIAL WORKFLOW", 1)[1]
    assert workflow.index("ANATOMICAL LOCATION FIRST") < workflow.index("PRESENCE")
    assert workflow.index("SAME-FOCUS CORRELATION") < workflow.index("DIAGNOSTIC FAMILY")
    assert "A shared disc level does not make an endplate focus and a facet focus the same lesion" in text


def test_diagnostic_schema_separates_screening_anatomy_from_reviewed_anatomy():
    output = analysis_prompt.LUMBAR_VERIFICATION.text.split("OUTPUT", 1)[1]
    example = llm_backend.extract_json_block(output)["verifications"][0]
    assert example["candidate"] == "<attention_id_or_null>"
    assert example["screening_structure"] == "<screening_anatomical_structure_or_null>"
    assert example["structure"] == "<verified_anatomical_structure_or_null>"
    assert example["level"] == "<verified_level_or_unclear>"
    assert example["vertebra"] is None
    assert example["screening_diagnosis"] is None


def test_same_level_anatomical_foci_keep_separate_ids_and_crossplane_locations():
    from modules.ai_imaging.eagle_eye_lumbar.screening_attention import normalize_attention
    rows = [{"assessment": "abnormal", "structure": structure, "level": "L4-L5",
             "vertebra": "L4" if structure == "endplate" else None,
             "locations": [
                 {"session": "sagittal", "frame": 4, "pane": "sagittal_t2", "box_2d": None},
                 {"session": "axial", "frame": 12, "pane": "axial_t2", "box_2d": None},
             ]} for structure in ("disc", "endplate", "facet_joint")]
    attention = normalize_attention({"findings": rows}, _package())
    assert [row["structure"] for row in attention["findings"]] == ["disc", "endplate", "facet_joint"]
    assert len({row["attention_id"] for row in attention["findings"]}) == 3
    assert attention["findings"][1]["vertebra"] == "L4"
    for row in attention["findings"]:
        assert [location["pane"] for location in row["locations"]] == ["sagittal_t2", "axial_t2"]


def test_legacy_labels_and_free_text_do_not_reach_diagnostic_reader():
    raw = {"findings": [{"level": "L4-L5", "candidate": "disc_extrusion",
                         "grade": 3, "note": "malignant appearance",
                         "confidence": "high"}]}
    header = llm_backend._candidate_context("untrusted diagnosis", raw)
    assert "disc_extrusion" not in header
    assert "malignant appearance" not in header
    assert '"grade"' not in header
    assert '"structure": "disc"' in header


def test_unparseable_screening_is_not_raw_text_or_a_normal_exam():
    header = llm_backend._candidate_context("disc_extrusion guessed here", None)
    assert "disc_extrusion" not in header
    assert '"status": "unavailable"' in header


def test_planner_excludes_explicit_normals_without_losing_abnormal_anatomy():
    plan = build_evidence_plan("", {"findings": [
        {"level": "L1-L2", "structure": "disc", "assessment": "normal"},
        {"level": "L4-L5", "structure": "disc", "assessment": "abnormal",
         "confidence": "high", "key_frames": {"axial": [12, 13]}},
    ]}, None)
    assert [focus.level for focus in plan.focuses] == ["L4-L5"]
    assert plan.focuses[0].family == "disc"


def test_context_cannot_create_a_level_card_without_abnormal_screening_attention():
    plan = build_evidence_plan(
        "LEVEL MAP\n  L4-L5: axial frames 1-4\n  L5-S1: axial frames 5-8",
        {"findings": [{
            "level": "L5-S1", "structure": "disc", "assessment": "abnormal",
            "confidence": "high", "key_frames": {"axial": [6]},
        }]},
        {"context_attention_foci": [{
            "scope": "level_specific", "anatomic_focus": "L4-L5",
            "context_type": "discogenic", "confidence": "high",
        }]},
    )

    assert [focus.level for focus in plan.focuses] == ["L5-S1"]
    assert "context_only_focus_not_carded" in plan.warnings


def _package():
    images = [PackagedImage(Path("/synthetic") / name, "synthetic", session, index,
                            capture={"panes": {role: {"role": "primary"}}})
              for name, session, index, role in [
                  ("sag.png", "sagittal", 4, "sagittal_t2"),
                  ("t1.png", "sagittal", 5, "sagittal_t1"),
                  ("ax.png", "axial", 12, "axial_t2"),
              ]]
    return SimpleNamespace(images=images, session_dir=Path("/synthetic"))


def _attention(row):
    from modules.ai_imaging.eagle_eye_lumbar.screening_attention import normalize_attention
    return normalize_attention({"schema_version": "2.0.0", "findings": [row]}, _package())


def test_correspondence_keeps_each_original_capture_identity_and_box():
    result = _attention({"level": "L4-L5", "structure": "disc", "assessment": "abnormal",
                         "locations": [
                             {"session": "sagittal", "frame": 4, "pane": "sagittal_t2",
                              "box_2d": [200, 100, 400, 300]},
                             {"session": "sagittal", "frame": 5, "pane": "sagittal_t1",
                              "box_2d": [220, 420, 410, 600]},
                             {"session": "axial", "frame": 12, "pane": "axial_t2",
                              "box_2d": [300, 720, 500, 880]},
                         ]})
    focus = result["findings"][0]
    assert [loc["source_file"] for loc in focus["locations"]] == ["sag.png", "t1.png", "ax.png"]
    assert focus["key_frames"]["axial"] == [12]
    assert focus["locations"][0]["box_2d"] == [200, 100, 400, 300]
    assert result["correspondence_status"] == "model_proposed_not_geometry_verified"


def test_invalid_coordinates_and_frames_cannot_become_trusted_localization():
    result = _attention({"level": "L4-L5", "structure": "disc", "assessment": "abnormal",
                         "locations": [
                             {"session": "axial", "frame": 12, "pane": "axial_t2",
                              "box_2d": [0, 0, 1001, 200]},
                             {"session": "axial", "frame": 999, "pane": "axial_t2",
                              "box_2d": [0, 0, 100, 100]},
                         ]})
    assert len(result["findings"]) == 1  # Bad localization is not proof of normality.
    assert result["findings"][0]["locations"][0]["box_2d"] is None
    assert len(result["findings"][0]["locations"]) == 1
    assert result["warnings"]


def test_normals_are_removed_and_unassessable_is_not_normal():
    from modules.ai_imaging.eagle_eye_lumbar.screening_attention import normalize_attention
    result = normalize_attention({"schema_version": "2.0.0", "findings": [
        {"structure": "facet_joint", "assessment": "normal"},
        {"structure": "bone_marrow", "assessment": "not_assessable"},
    ]}, _package())
    assert result["findings"] == []
    assert result["not_assessable"][0]["structure"] == "bone_marrow"
    assert result["normal_count"] == 1
    assert result["status"] != "normal"
    assert "diagnosis" not in json.dumps(result["findings"])


@pytest.mark.parametrize("box", [
    [0, 0, float("nan"), 100], [0, 0, float("inf"), 100],
    [0, 0, 10 ** 1000, 100], [0, 0, True, 100],
    [400, 300, 200, 100], [0, 0, 0, 100], {"x": 10},
])
def test_malformed_boxes_preserve_focus_but_are_never_forwarded(box):
    result = _attention({"structure": "disc", "assessment": "abnormal",
                         "locations": [{"session": "axial", "frame": 12,
                                        "pane": "axial_t2", "box_2d": box}]})
    assert result["findings"][0]["locations"][0]["box_2d"] is None
    assert "screening_box_invalid" in result["warnings"]


def test_nonlayout_box_is_not_mislabeled_as_original_capture_coordinates():
    from modules.ai_imaging.eagle_eye_lumbar.screening_attention import normalize_attention
    package = _package()
    package.images[-1].evidence_mode = "focused-v1"
    result = normalize_attention({"findings": [{
        "structure": "disc", "assessment": "abnormal",
        "locations": [{"session": "axial", "frame": 12,
                       "pane": "axial_t2", "box_2d": [0, 0, 100, 100]}],
    }]}, package)
    assert result["findings"][0]["locations"][0]["box_2d"] is None
    assert "screening_box_nonlayout_transform_unavailable" in result["warnings"]


def test_reference_panes_and_wrong_session_cannot_supply_axial_anchors():
    result = _attention({"structure": "disc", "assessment": "abnormal",
                         "locations": [{"session": "sagittal", "frame": 4,
                                        "pane": "axial_t2", "box_2d": None}]})
    assert result["findings"][0]["key_frames"]["axial"] == []
    assert "screening_location_not_in_capture_inventory" in result["warnings"]


def test_raw_response_is_not_mutated_and_untrusted_fields_cannot_leak():
    from modules.ai_imaging.eagle_eye_lumbar.screening_attention import normalize_attention
    raw = {"findings": [{"candidate": "disc_extrusion", "note": "unsafe label",
                         "key_frames": {"axial": [12]}, "locations": []}]}
    original = copy.deepcopy(raw)
    result = normalize_attention(raw, _package())
    assert raw == original
    assert result["findings"][0]["key_frames"]["axial"] == [12]
    assert "unsafe label" not in json.dumps(result)
    assert "disc_extrusion" not in json.dumps(result)


def test_unknown_level_and_malformed_rows_are_not_silently_normalized_to_normal():
    from modules.ai_imaging.eagle_eye_lumbar.screening_attention import normalize_attention
    result = normalize_attention({"findings": [None,
        {"assessment": [], "structure": "disc"},
        {"assessment": "abnormal", "structure": "disc", "level": "L1-L5",
         "laterality": "screen_left", "diagnosis": "secret label"},
    ]}, _package())
    assert result["status"] == "degraded"
    assert result["findings"][0]["level"] == "unclear"
    assert result["findings"][0]["laterality"] == "indeterminate"
    assert "secret label" not in json.dumps(result)


def test_duplicate_screening_rows_become_one_canonical_crossplane_focus():
    from modules.ai_imaging.eagle_eye_lumbar.screening_attention import normalize_attention

    result = normalize_attention({"findings": [
        {
            "assessment": "abnormal", "structure": "disc", "level": "L4-L5",
            "laterality": "right", "confidence": "moderate",
            "locations": [{"session": "sagittal", "frame": 4,
                           "pane": "sagittal_t2", "box_2d": [200, 100, 400, 300]}],
        },
        {
            "assessment": "abnormal", "structure": "disc", "level": "L4-L5",
            "laterality": "right", "confidence": "high",
            "locations": [{"session": "axial", "frame": 12,
                           "pane": "axial_t2", "box_2d": [300, 700, 500, 880]}],
        },
    ]}, _package())

    assert len(result["findings"]) == 1
    focus = result["findings"][0]
    assert focus["attention_id"] == "attention-01"
    assert focus["confidence"] == "high"
    assert focus["laterality"] == "right"
    assert [item["pane"] for item in focus["locations"]] == ["sagittal_t2", "axial_t2"]
    assert focus["key_frames"] == {"axial": [12], "sagittal": [4]}


def test_normal_abnormal_contradiction_is_resolved_once_for_screening_sensitivity():
    from modules.ai_imaging.eagle_eye_lumbar.screening_attention import normalize_attention

    result = normalize_attention({"findings": [
        {"assessment": "normal", "structure": "disc", "level": "L5-S1",
         "confidence": "high"},
        {"assessment": "abnormal", "structure": "disc", "level": "L5-S1",
         "confidence": "high", "locations": [
             {"session": "axial", "frame": 12, "pane": "axial_t2",
              "box_2d": [300, 700, 500, 880]},
         ]},
    ]}, _package())

    assert len(result["findings"]) == 1
    assert result["not_assessable"] == []
    assert result["findings"][0]["assessment"] == "abnormal"
    assert result["findings"][0]["confidence"] == "moderate"
    assert result["normal_count"] == 1
    assert "screening_assessment_conflict_resolved_abnormal" in result["warnings"]


def test_conflicting_sides_are_not_forwarded_as_competing_localizations():
    from modules.ai_imaging.eagle_eye_lumbar.screening_attention import normalize_attention

    result = normalize_attention({"findings": [
        {"assessment": "abnormal", "structure": "lateral_recess", "level": "L4-L5",
         "laterality": "left", "confidence": "high"},
        {"assessment": "abnormal", "structure": "lateral_recess", "level": "L4-L5",
         "laterality": "right", "confidence": "high"},
    ]}, _package())

    assert len(result["findings"]) == 1
    assert result["findings"][0]["laterality"] == "bilateral"
    context = llm_backend._candidate_context("ignored raw text", {"findings": [
        {"assessment": "abnormal", "structure": "lateral_recess", "level": "L4-L5",
         "laterality": "left", "confidence": "high"},
        {"assessment": "abnormal", "structure": "lateral_recess", "level": "L4-L5",
         "laterality": "right", "confidence": "high"},
    ]})
    assert context.count('"attention_id"') == 1
    assert '"laterality": "left"' not in context
    assert '"laterality": "right"' not in context


def test_diagnostic_handoff_omits_non_actionable_screening_audit_noise():
    from modules.ai_imaging.eagle_eye_lumbar.screening_attention import (
        attention_context,
        normalize_attention,
    )

    attention = normalize_attention({"findings": [
        {"assessment": "normal", "structure": "facet_joint", "level": "L4-L5"},
        {"assessment": "abnormal", "structure": "disc", "level": "L5-S1",
         "confidence": "high"},
    ]}, _package())
    context = attention_context(attention)

    assert '"normal_count"' not in context
    assert '"warnings"' not in context
    assert '"handoff_quality"' in context
    assert "screening_focus_without_valid_location" in context
    assert "one canonical row per anatomical focus" in context


def test_screening_prompt_requires_one_resolved_row_instead_of_contradictory_duplicates():
    text = " ".join(analysis_prompt.LUMBAR_SCREENING.text.split())
    assert "Never emit both normal and abnormal for the same anatomical focus" in text
    assert "merge their locations into one row" in text
    assert "low confidence only if a direct visible feature supports the row" in text


def test_screening_contract_ranks_visible_abnormality_without_diagnosing_it():
    text = " ".join(analysis_prompt.LUMBAR_SCREENING.text.split())

    assert '"schema_version": "2.7.0"' in text
    assert '"visual_salience": "marked"' in text
    assert '"within_study_priority": "dominant"' in text
    assert '"slice_persistence": "three_or_more_adjacent_slices"' in text
    assert "Visual salience is not diagnostic severity or clinical urgency" in text
    assert "Do NOT name a disease, differential, morphology subtype, grade or severity" in text


def test_normalizer_preserves_only_allowlisted_observable_priority_fields():
    from modules.ai_imaging.eagle_eye_lumbar.screening_attention import normalize_attention

    result = normalize_attention({"schema_version": "2.3.0", "findings": [{
        "assessment": "abnormal",
        "structure": "disc",
        "level": "L5-S1",
        "confidence": "high",
        "visual_salience": "marked",
        "within_study_priority": "dominant",
        "slice_persistence": "three_or_more_adjacent_slices",
        "observable_features": {
            "signal_change": "definite",
            "contour_change": "marked",
            "space_effacement": "marked",
            "visible_neural_relationship": "compression",
            "diagnosis": "must not cross the boundary",
        },
    }]}, _package())

    focus = result["findings"][0]
    assert focus["visual_salience"] == "marked"
    assert focus["within_study_priority"] == "dominant"
    assert focus["slice_persistence"] == "three_or_more_adjacent_slices"
    assert focus["observable_features"] == {
        "signal_change": "definite",
        "contour_change": "marked",
        "space_effacement": "marked",
        "visible_neural_relationship": "compression",
    }
    assert "diagnosis" not in json.dumps(result)


def test_dominant_caudal_focus_survives_the_four_focus_budget():
    findings = [
        {
            "attention_id": f"attention-{index:02d}",
            "assessment": "abnormal",
            "structure": "disc",
            "level": level,
            "confidence": "high",
            "visual_salience": "subtle",
            "within_study_priority": "minor",
        }
        for index, level in enumerate(
            ("L1-L2", "L2-L3", "L3-L4", "L4-L5"), start=1
        )
    ]
    findings.append({
        "attention_id": "attention-05",
        "assessment": "abnormal",
        "structure": "disc",
        "level": "L5-S1",
        "confidence": "high",
        "visual_salience": "marked",
        "within_study_priority": "dominant",
        "slice_persistence": "three_or_more_adjacent_slices",
    })

    plan = build_evidence_plan("", {"findings": findings}, None, max_focuses=4)

    assert [focus.level for focus in plan.focuses][0] == "L5-S1"
    assert "L5-S1" in [focus.level for focus in plan.focuses]
    assert plan.focuses[0].visual_salience == "marked"
    assert plan.focuses[0].within_study_priority == "dominant"
    assert "focus_limit_applied" in plan.warnings


def test_over_capacity_dominant_set_is_never_silently_truncated():
    findings = [
        {
            "attention_id": f"attention-{index:02d}",
            "assessment": "abnormal",
            "structure": "disc",
            "level": level,
            "confidence": "high",
            "visual_salience": "marked",
            "within_study_priority": "dominant",
        }
        for index, level in enumerate(
            ("L1-L2", "L2-L3", "L3-L4", "L4-L5", "L5-S1"), start=1
        )
    ]

    plan = build_evidence_plan("", {"findings": findings}, None, max_focuses=4)

    assert len(plan.focuses) == 4
    assert "focus_limit_applied" in plan.warnings
    assert "dominant_focus_capacity_exceeded" in plan.warnings


def test_v23_missing_priority_contract_is_visible_to_the_diagnostic_handoff():
    from modules.ai_imaging.eagle_eye_lumbar.screening_attention import (
        attention_context,
        normalize_attention,
    )

    attention = normalize_attention({"schema_version": "2.3.0", "findings": [{
        "assessment": "abnormal",
        "structure": "disc",
        "level": "L5-S1",
        "confidence": "high",
    }]}, _package())
    context = attention_context(attention)

    assert attention["status"] == "degraded"
    assert "screening_priority_contract_incomplete" in attention["warnings"]
    assert "screening_priority_contract_incomplete" in context
    assert "must not be copied into diagnostic severity" in context


def test_missing_atlas_tile_identity_is_material_to_the_diagnostic_handoff():
    from modules.ai_imaging.eagle_eye_lumbar.screening_attention import attention_context

    context = attention_context({
        "status": "degraded",
        "correspondence_status": "deterministic_patient_geometry_validation",
        "findings": [],
        "not_assessable": [],
        "warnings": ["screening_tile_not_in_inventory"],
    })

    assert '"status": "degraded"' in context
    assert '"issues": [' in context
    assert "screening_tile_not_in_inventory" in context


def test_diagnostic_prompt_scopes_each_attention_to_one_level_card():
    text = " ".join(analysis_prompt.LUMBAR_VERIFICATION.text.split())

    assert "FOCUSED V5 LEVEL CARDS" in text
    assert "one self-contained diagnostic card per resolved subject level" in text
    assert "Resolve an attention_id using only its bound card" in text
    assert "A citation outside its allowed frame set" in text
    assert "must never transfer a finding" in text


def test_diagnostic_prompt_is_card_first_and_records_the_exact_input_binding():
    text = " ".join(analysis_prompt.LUMBAR_VERIFICATION.text.split())

    assert "CARD-FIRST DIAGNOSTIC WORKFLOW" in text
    assert "Process cards in request IMAGE order" in text
    assert "bind the PNG to the immediately preceding CARD_METADATA_JSON" in text
    assert "one independent decision for every attention_id listed in that card" in text
    assert "Do not begin diagnostic classification until the binding is valid" in text
    assert '"card_id": "<bound_card_id>"' in text
    assert '"card_image_index": 1' in text
    assert '"card_kind": "<lumbar_level_or_additional_findings>"' in text


def test_diagnostic_prompt_does_not_create_unbound_v5_findings_from_context():
    text = " ".join(analysis_prompt.LUMBAR_VERIFICATION.text.split())

    assert "Context cannot create a diagnostic card" in text
    assert "An unmatched context focus is not permission to diagnose an unbound level" in text
    assert "CARD-LOCAL SAFETY CHECK" in text
    assert "MANDATORY SAFETY SWEEP AFTER THE CANDIDATES" not in text
    assert "re-scan the complete MRI package" not in text


def test_diagnostic_output_schema_does_not_seed_a_level_specific_diagnosis():
    output = analysis_prompt.LUMBAR_VERIFICATION.text.split("OUTPUT", 1)[1]

    assert '"final_diagnosis": "<best_supported_diagnosis_or_null>"' in output
    assert '"level": "<verified_level_or_unclear>"' in output
    assert '"final_diagnosis": "disc_extrusion"' not in output
    assert "L4-L5: Central disc extrusion" not in output
