"""Physical side and complete neural-compartment handoff regression guards."""
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from modules.ai_imaging.eagle_eye_lumbar import anatomy_cards, atomic_pipeline, screening_evidence
from modules.ai_imaging.eagle_eye_lumbar.focus_evidence import FocusedEvidenceError
from modules.ai_imaging.eagle_eye_lumbar.llm_package import AnalysisPackage, PackagedImage
from test_eagle_eye_anatomy_gate import _atlas_package, _anatomy_map


def compartment_rows(request_key, levels=None, findings=()):
    levels = levels or [{"level": "L4-L5", "axial_group_id": "axial-group-05"}]
    structures = ("lateral_recess", "nerve_root") if request_key == "canal_neural" else ("neural_foramen",)
    rows = []
    for level in levels:
        for structure in structures:
            for side in ("right", "left"):
                matches = [f for f in findings if f.get("structure") == structure
                           and f.get("level") == level["level"]
                           and f.get("laterality") in (side, "bilateral")]
                first = (int(level["axial_group_id"].rsplit("-", 1)[1]) - 1) * 3 + 1
                rows.append({"level": level["level"], "axial_group_id": level["axial_group_id"],
                             "structure": structure, "laterality": side,
                             "assessment": matches[0].get("assessment", "abnormal") if matches else "normal",
                             "tile_ids": [f"axial-series-a:{first:04d}"],
                             "reason": "Directly inspected the bounded compartment on the cited image."})
    return rows


def _request(key="canal_neural"):
    return next(r for r in atomic_pipeline.SCREENING_REQUESTS if r.key == key)


def _outcome(key="canal_neural", findings=()):
    observation = {"level": "L4-L5", "axial_group_id": "axial-group-05", "assessment": "normal",
                   "caliber": "preserved", "csf_visibility": "preserved", "visual_basis": "preserved_caliber",
                   "myelographic_correlation": "not_available", "axial_tile_ids": ["axial-series-a:0013"],
                   "reason": "Preserved central caliber."}
    return {"structured": {"schema_version": atomic_pipeline.ATOMIC_SCREENING_SCHEMA_VERSION,
                           "screening_request": key, "findings": list(findings),
                           "central_canal_observations": [observation] if key == "canal_neural" else [],
                           "compartment_observations": compartment_rows(key, findings=findings)}}


def test_reversed_sagittal_side_is_corrected_without_changing_membership(tmp_path):
    atlas = _atlas_package(tmp_path)
    for page in atlas.evidence_audit["pages"]:
        for tile in page["tiles"]:
            if tile["role"].startswith("sagittal"):
                tile["mapping"]["origin"][0] = -float(tile["source_slice"])
    source = deepcopy(atlas.evidence_audit)
    proposal = _anatomy_map()
    normalized = anatomy_cards.normalize_anatomy_map(atlas, proposal)
    assert normalized["sagittal_planes"]["sagittal_t2"]["right_paracentral"].endswith(":0008")
    assert normalized["sagittal_planes"]["sagittal_t2"]["midline"].endswith(":0006")
    groups = {x["group_id"]: x["anatomical_role"] for x in normalized["sagittal_group_assignments"]}
    assert groups["sagittal-group-03"] == "right_lateral"
    assert atlas.evidence_audit == source
    assert proposal == _anatomy_map()


def test_noncanonical_axial_cannot_be_sent_with_canonical_side_instructions(monkeypatch):
    source = SimpleNamespace(source_ordinal=1)
    monkeypatch.setattr(screening_evidence, "_captured_axial_sequence", lambda *a: [SimpleNamespace(source=source, capture_frame=1)])
    monkeypatch.setattr(screening_evidence, "intensity_window_slices", lambda *a: (0, 1))
    monkeypatch.setattr(screening_evidence, "_display_dicom_slice", lambda *a: np.zeros((8, 8)))
    monkeypatch.setattr(screening_evidence, "_axial_roi", lambda a, s: (a, (0, 0, 8, 8), (1, 1)))
    monkeypatch.setattr(screening_evidence, "_tile_record", lambda **kw: {})
    monkeypatch.setattr(screening_evidence, "horizontal_patient_orientation_for_slice", lambda *a: ("L", "R"))
    with pytest.raises(FocusedEvidenceError, match="canonical"):
        screening_evidence._axial_tiles(None, SimpleNamespace(slices=[]), "axial", "a", "axial_t2", [])


@pytest.mark.parametrize("key", ["canal_neural", "foraminal"])
def test_missing_side_checklist_is_not_a_normal_screen(key):
    outcome = _outcome(key)
    outcome["structured"].pop("compartment_observations")
    assert "compartment_observations_missing" in atomic_pipeline.screening_outcome_errors(_request(key), outcome)


def test_recess_positive_can_coexist_with_normal_central_canal():
    finding = {"structure": "lateral_recess", "level": "L4-L5", "laterality": "right", "assessment": "abnormal"}
    assert atomic_pipeline.screening_outcome_errors(_request(), _outcome(findings=[finding])) == []


def test_abnormal_recess_must_reach_findings_and_diagnosis():
    outcome = _outcome()
    outcome["structured"]["compartment_observations"][0]["assessment"] = "abnormal"
    assert any("finding_conflict" in e for e in atomic_pipeline.screening_outcome_errors(_request(), outcome))


def test_cannot_substitute_opposite_side_or_duplicate_one_side():
    outcome = _outcome("foraminal")
    outcome["structured"]["compartment_observations"][1] = deepcopy(outcome["structured"]["compartment_observations"][0])
    assert atomic_pipeline.screening_outcome_errors(_request("foraminal"), outcome)


def test_compartment_evidence_must_belong_to_the_same_level(tmp_path):
    cards = anatomy_cards.prepare_anatomy_cards(_atlas_package(tmp_path), _anatomy_map())
    package = anatomy_cards.screening_package_for(cards, "foraminal")
    outcome = _outcome("foraminal")
    outcome["structured"]["compartment_observations"][0]["tile_ids"] = ["axial-series-a:0001"]
    assert any("wrong_group_evidence" in e for e in atomic_pipeline.screening_outcome_errors(_request("foraminal"), outcome, package))


def test_neural_summary_keeps_central_recess_and_foramen_separate():
    canal = _outcome()
    foraminal = _outcome("foraminal")
    summary = atomic_pipeline.merge_screening_outcomes([(_request(), canal), (_request("foraminal"), foraminal)])
    coverage = summary["structured"]["neural_compartment_coverage"]
    assert len(coverage) == 7
    assert {x["structure"] for x in coverage} == {"central_canal", "lateral_recess", "nerve_root", "neural_foramen"}


def test_unassessable_neural_compartment_requires_review():
    outcome = _outcome()
    outcome["structured"]["compartment_observations"][0]["assessment"] = "not_assessable"
    result = atomic_pipeline.merge_screening_outcomes([(_request(), outcome)])
    assert any("neural_compartment_not_assessable" in w for w in result["structured"]["warnings"])


def test_card_request_uses_actual_card_and_preserves_only_clinical_context(tmp_path):
    image = PackagedImage(tmp_path / "synthetic.png", "Six-panel T2 disc card", "focus", 1,
                          card_payload={"card_metadata": {"card_id": "c1", "subject_level": "L4-L5", "structure_group": "disc"}})
    header = "layout: 1 x 3 - panel 2 = sagittal_t1\nlocalisers: old capture\nCLINICAL CONTEXT EXTRACTED BY THE PARALLEL MULTI-SOURCE READER.\nSynthetic context retained."
    package = AnalysisPackage(tmp_path, "s", "lumbar_mri", None, header, [image])
    actual = atomic_pipeline.verification_package_for(package, 1).header
    assert "layout: 1 x 3" not in actual
    assert "localisers: old capture" not in actual
    assert "Synthetic context retained." in actual
    assert "patient right" in actual.lower() and "viewer left" in actual.lower()


def test_all_atomic_prompts_state_axial_patient_side_and_compartment_coverage():
    base = SimpleNamespace(model_feature="screening", model_default="synthetic")
    for request in atomic_pipeline.SCREENING_REQUESTS:
        prompt = atomic_pipeline.screening_stage_for(base, request).text.lower()
        assert "patient right" in prompt and "viewer left" in prompt
        if request.key in ("canal_neural", "foraminal"):
            assert "compartment_observations" in prompt


def test_physical_side_correction_cannot_move_the_selected_midline(tmp_path):
    atlas = _atlas_package(tmp_path)
    proposal = _anatomy_map()
    planes = proposal["sagittal_planes"]["sagittal_t2"]
    planes["midline"], planes["right_paracentral"] = planes["right_paracentral"], planes["midline"]
    with pytest.raises(anatomy_cards.AnatomyCardError, match="midline"):
        anatomy_cards.normalize_anatomy_map(atlas, proposal)


def test_normal_compartment_cannot_hide_a_positive_finding():
    finding = {"structure": "neural_foramen", "level": "L4-L5", "laterality": "bilateral", "assessment": "abnormal"}
    outcome = _outcome("foraminal", [finding])
    outcome["structured"]["compartment_observations"][1]["assessment"] = "normal"
    assert any("finding_conflict" in e for e in atomic_pipeline.screening_outcome_errors(_request("foraminal"), outcome))


def test_foraminal_sagittal_evidence_must_match_patient_side(tmp_path):
    cards = anatomy_cards.prepare_anatomy_cards(_atlas_package(tmp_path), _anatomy_map())
    package = anatomy_cards.screening_package_for(cards, "foraminal")
    outcome = _outcome("foraminal")
    outcome["structured"]["compartment_observations"] = compartment_rows("foraminal", _anatomy_map()["axial_levels"])
    row = outcome["structured"]["compartment_observations"][0]
    row["tile_ids"] = ["sagittal-series-a:0002"]
    assert atomic_pipeline.screening_outcome_errors(_request("foraminal"), outcome, package) == []
    row["tile_ids"] = ["sagittal-series-a:0010"]
    assert any("wrong_group_evidence" in e for e in atomic_pipeline.screening_outcome_errors(_request("foraminal"), outcome, package))


def test_missing_one_neural_compartment_fails_complete_level_coverage(tmp_path):
    cards = anatomy_cards.prepare_anatomy_cards(_atlas_package(tmp_path), _anatomy_map())
    package = anatomy_cards.screening_package_for(cards, "foraminal")
    outcome = _outcome("foraminal")
    outcome["structured"]["compartment_observations"] = compartment_rows("foraminal", _anatomy_map()["axial_levels"])
    outcome["structured"]["compartment_observations"].pop()
    assert "compartment_observation_level_side_coverage" in atomic_pipeline.screening_outcome_errors(_request("foraminal"), outcome, package)
