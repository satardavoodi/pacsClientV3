"""Keep diagnostic grading distinct from root observations and screening."""

from modules.ai_imaging.eagle_eye_lumbar import analysis_prompt as prompts
from modules.ai_imaging.eagle_eye_lumbar import grading


def test_root_observations_have_their_own_version_and_non_severity_labels():
    assert grading.ROOT_OBSERVATION_VERSION == "1.0.0"
    assert [item.effect for item in grading.ROOT_OBSERVATIONS] == [
        "none", "contact", "deviation", "compression",
    ]
    assert "without displacement or compression" in grading.ROOT_OBSERVATIONS[1].criteria
    assert "without compression" in grading.ROOT_OBSERVATIONS[2].criteria
    assert "compressed" in grading.ROOT_OBSERVATIONS[3].criteria


def test_recess_contract_does_not_reuse_root_deviation_as_grade_two():
    assert "without compression" not in grading.LATERAL_RECESS.grades[2].criteria
    assert "no objective compression" in grading.LATERAL_RECESS.grades[1].criteria
    assert "residual CSF" in grading.LATERAL_RECESS.grades[2].criteria
    assert "obliteration" in grading.LATERAL_RECESS.grades[3].criteria


def test_new_contract_versions_do_not_relabel_legacy_stage_prompts():
    assert prompts.LUMBAR_SCREENING.version == "2.7.0"
    assert prompts.LUMBAR_VERIFICATION.version == "5.2.0"
    assert prompts.LUMBAR_CLINICAL_CONTEXT.version == "2.3.0"
    for stage in (prompts.LUMBAR_VERIFICATION,):
        assert grading.prompt_rubric() in stage.text
        assert "A CSF-area asymmetry alone" in stage.text
        assert "keep root observations in the finding/reason text" in stage.text
    assert grading.prompt_rubric() not in prompts.LUMBAR_CLINICAL_CONTEXT.text
    assert grading.prompt_rubric() not in prompts.LUMBAR_SCREENING.text
