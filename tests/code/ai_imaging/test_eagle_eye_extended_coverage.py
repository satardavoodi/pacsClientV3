"""Extra anatomical coverage must not shift lumbar labels or imply diagnosis."""
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_lumbar import anatomy_cards, atomic_pipeline
from test_eagle_eye_anatomy_gate import _atlas_package, _anatomy_map


LEVELS = ("T11-T12", "T12-L1", "L1-L2", "L2-L3", "L3-L4", "L4-L5", "L5-S1")


def test_seven_groups_preserve_lumbar_labels_and_context_membership(tmp_path):
    atlas = _atlas_package(tmp_path, 7)
    result = anatomy_cards.normalize_anatomy_map(atlas, _anatomy_map(LEVELS))
    assert [x["level"] for x in result["axial_levels"]] == list(LEVELS[1:])
    assert result["axial_levels"][-1]["axial_frames"] == [19, 21]
    context, = result["context_axial_levels"]
    assert context["level"] == "T11-T12"
    assert context["axial_group_id"] == "axial-group-01"
    assert context["axial_frames"] == [1, 3]
    assert [x["capture_frame"] for x in context["source_tiles"]] == [1, 2, 3]
    axial = [r for r in result["group_integrity"]["groups"] if r["series_role"] == "axial_t2"]
    assert len(axial) == 7
    assert result["coverage"]["not_assessed_levels"] == ["T11-T12"]


def test_context_is_retained_but_not_reassigned_to_lumbar_screening(tmp_path):
    atlas = _atlas_package(tmp_path, 7)
    cards = anatomy_cards.prepare_anatomy_cards(atlas, _anatomy_map(LEVELS))
    assert all(image.path.exists() for image in atlas.images)
    assert cards.evidence_audit["warnings"]
    for request in atomic_pipeline.SCREENING_REQUESTS:
        package = anatomy_cards.screening_package_for(cards, request.key)
        assert "outside the lumbar diagnostic scope" in package.header
        assert "T11-T12" in package.header
        tiles = [t for p in package.evidence_audit["pages"] for t in p["tiles"] if t.get("role") == "axial_t2"]
        assert all(t["capture_frame"] >= 4 for t in tiles)
        if tiles:
            assert set(t["capture_frame"] for t in tiles) == set(range(4, 22))
    merged = atomic_pipeline.merge_screening_outcomes([], anatomy_map=cards.evidence_audit["anatomy_map"])
    assert [r["level"] for r in merged["structured"]["level_map"]] == list(LEVELS[1:])
    assert any("T11-T12" in warning for warning in merged["warnings"])


@pytest.mark.parametrize("bad_level", ["T99-T100", "L5-S1", "", "unclear"])
def test_extra_group_does_not_waive_unknown_or_duplicate_identity(tmp_path, bad_level):
    reply = _anatomy_map(LEVELS)
    reply["axial_levels"][0]["level"] = bad_level
    with pytest.raises(anatomy_cards.AnatomyCardError) as exc:
        anatomy_cards.normalize_anatomy_map(_atlas_package(tmp_path, 7), reply)
    assert exc.value.code == "anatomy_map_level_identity_conflict"


def test_missing_context_member_is_not_silently_ignored(tmp_path):
    atlas = _atlas_package(tmp_path, 7)
    # A missing representative still fails at the existing identity boundary.
    atlas.evidence_audit["pages"][-1]["tiles"].pop(1)
    with pytest.raises(anatomy_cards.AnatomyCardError):
        anatomy_cards.normalize_anatomy_map(atlas, _anatomy_map(LEVELS))


def test_mapping_prompt_explains_extended_coverage_without_positional_labels():
    stage = atomic_pipeline.anatomy_mapping_stage_for(SimpleNamespace(
        model_feature="eagle_eye_screening", model_default="synthetic-model"))
    assert "T11-T12" in stage.text
    assert "outside the lumbar diagnostic scope" in stage.text
    assert "Do not infer a level" in stage.text


def test_previous_mapping_schema_can_be_revalidated_without_rewriting_response(tmp_path):
    reply = _anatomy_map(LEVELS)
    reply["schema_version"] = "1.8.0"
    result = anatomy_cards.normalize_anatomy_map(_atlas_package(tmp_path, 7), reply)
    assert reply["schema_version"] == "1.8.0"
    assert result["schema_version"] == anatomy_cards.ANATOMY_CARD_SCHEMA_VERSION


def test_context_only_study_cannot_be_reported_as_normal_lumbar(tmp_path):
    reply = _anatomy_map(("T11-T12",))
    with pytest.raises(anatomy_cards.AnatomyCardError) as exc:
        anatomy_cards.normalize_anatomy_map(_atlas_package(tmp_path, 1), reply)
    assert exc.value.code == "anatomy_map_lumbar_coverage_missing"


def test_context_pathology_cannot_enter_lumbar_diagnosis(tmp_path):
    result = anatomy_cards.normalize_anatomy_map(_atlas_package(tmp_path, 7), _anatomy_map(LEVELS))
    request = next(r for r in atomic_pipeline.SCREENING_REQUESTS if r.key == "disc")
    outcome = {"structured": {"findings": [{"level": "T11-T12", "structure": "disc", "assessment": "abnormal"}]}}
    merged = atomic_pipeline.merge_screening_outcomes([(request, outcome)], anatomy_map=result)
    assert not merged["structured"]["findings"]
    assert "atomic_screening_outside_lumbar_scope:T11-T12" in merged["warnings"]


def test_extra_context_is_reported_but_not_a_false_numbering_conflict(monkeypatch):
    from modules.ai_imaging.eagle_eye_lumbar import llm_backend
    seen = []
    def audit(_screen, _report, slabs):
        seen.extend(slabs)
        return {"status": "consistent", "slabs": []}
    monkeypatch.setattr(llm_backend.evidence_request, "audit_level_maps", audit)
    monkeypatch.setattr(llm_backend, "_audit_verification_card_scope", lambda *a: {"status": "not_applicable"})
    package = SimpleNamespace(evidence_audit={"measured_slabs": [[1, 3], [4, 6]]})
    started = {"anatomy_coverage": {"context_axial_frames": [[1, 3]]},
               "warnings": ["Outside lumbar diagnostic scope: T11-T12. Pathology was not assessed."]}
    report = llm_backend._guard_verification_report(package, "", "Synthetic report", started)
    assert seen == [[4, 6]]
    assert "T11-T12" in report
    assert started["review_required"]
    assert "level_assignment_unavailable" not in started["warnings"]
