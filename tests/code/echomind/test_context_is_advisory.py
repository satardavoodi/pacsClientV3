"""Guard: the regional context is guidance, not a report skeleton (2026-08-09).

OBSERVED. Patient 53626, a hysterosalpingogram. Region gate `abdomen`, so the prompt
carried the plain abdominal film block, and the report came back:

    Bowel gas pattern:        nonobstructive, no dilated small-bowel or colonic loops
    Free intraperitoneal air: none identified, limited on a supine examination
    Organ outlines:           renal, hepatic and splenic outlines within normal limits

on a fluoroscopic study of the uterus and tubes. The model did exactly what the prompt
told it to: "Group under the headings in REPORTING CONTEXT".

OWNER DECISION. The fix is NOT a rigid template per study type — "it is not practical
to create a separate rigid template for every possible projection, contrast technique,
procedure subtype". The regional content is guidance; the EXAMINATION decides the
report; standard radiology reporting practice is the fallback when the supplied
context does not describe the study.

The hierarchy the prompt must now express:

    study/procedure + transcript + modality + regional context + reporting standards
        -> reasoning -> the report the actual examination calls for

After the change the same dictation produced Uterine Cavity / Fallopian Tubes /
Peritoneal Spill, with no plain-film language and no HSG template authored anywhere.
"""

import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind.viewer_chat import turbo_prompt as tp             # noqa: E402
from modules.EchoMind.viewer_chat import turbo_template as tt           # noqa: E402

HSG = {"regions": ["abdomen"], "subtype": ["xr_hsg"]}


def _prompt(profile=None, modality="RADIOLOGY"):
    return tp.build_turbo_system_prompt(modality, "", profile=profile or HSG)


def _flat(s):
    """Whitespace-normalised. These are hard-wrapped paragraphs, so a phrase that
    reads as one sentence is split across a newline in the source."""
    return " ".join(str(s).split())


# ── the hierarchy is stated ──────────────────────────────────────────────────

def test_the_examination_outranks_the_regional_context():
    assert "THE EXAMINATION THAT WAS ACTUALLY PERFORMED" in tt.PRECEDENCE
    i = tt.PRECEDENCE.index("THE EXAMINATION THAT WAS ACTUALLY PERFORMED")
    j = tt.PRECEDENCE.index("REPORTING CONTEXT")
    assert i < j, "the regional context is still listed above the examination"


def test_the_regional_context_is_labelled_advisory_in_precedence():
    seg = _flat(tt.PRECEDENCE[tt.PRECEDENCE.index("REPORTING CONTEXT"):])
    assert "ADVISORY" in seg
    assert "checklist you must complete" in seg


def test_the_build_order_starts_from_the_examination_not_the_region():
    assert "Identify the EXAMINATION that was actually performed" in tt.RULES_NORMAL
    steps = tt.RULES_NORMAL
    assert steps.index("Identify the EXAMINATION") < steps.index("REPORTING CONTEXT")


@pytest.mark.parametrize("probe", [
    "Leave out what it lists that this examination does not show",
    "add what it omits that this examination does show",
])
def test_the_rules_permit_both_directions(probe):
    """The old wording only ever allowed WIDENING ('not a limit on what you may
    report'). Leaving items OUT is the direction that was missing, and the one the
    hysterosalpingogram needed."""
    assert probe in _flat(tt.RULES_NORMAL)


def test_the_wrong_report_is_named_as_wrong():
    assert "THE REGIONAL CONTEXT IS GUIDANCE, NOT A SKELETON" in tt.RULES_NORMAL
    flat = _flat(tt.RULES_NORMAL)
    assert "hysterosalpingogram" in flat.lower()
    assert "is a WRONG report, not a thorough one" in flat


def test_the_rsna_fallback_is_explicit():
    """When the supplied context does not describe the examination, standard practice
    for that examination is the fallback — not the template that happened to arrive."""
    flat = _flat(tt.RULES_NORMAL)
    assert "established radiology reporting practice" in flat
    assert "RSNA-style section" in flat
    assert "rather than filling in the template you were handed" in flat


def test_routine_studies_still_get_covered_fully():
    """Advisory must not read as 'omit whatever you like'. Some examinations are
    routine enough that nearly every listed item applies."""
    flat = _flat(tt.RULES_NORMAL)
    assert "nearly every item in the block applies" in flat
    assert "cover nearly all of them" in flat


def test_a_structure_the_study_cannot_assess_is_never_normal():
    assert "must not appear as a normal finding" in _flat(tt.RULES_NORMAL)


# ── the rendered blocks say it too ───────────────────────────────────────────

def test_the_region_block_header_is_advisory():
    got = _flat(_prompt())
    assert "ADVISORY — one block per region" in got
    assert "NOT a checklist and NOT a report skeleton" in got
    assert "leave out the parts that do not" in got


def test_the_normal_reference_is_labelled_selective():
    assert "use the items this examination" in _prompt()


def test_the_study_type_block_defines_the_report():
    """It used to read 'within the region above', which subordinated the actual
    examination to a coarse gate."""
    got = _prompt()
    assert "THE EXAMINATION THAT WAS PERFORMED" in got
    assert "Where the two disagree, this wins." in _flat(got)
    assert "within the region above" not in _flat(got)


# ── what must NOT have changed ───────────────────────────────────────────────

def test_the_pathology_half_is_untouched():
    """Advisory applies to GENERATION. Pathology is transcription and stays absolute."""
    flat = _flat(tt.RULES_PATHOLOGICAL)
    assert "The transcript is the only source of pathology." in flat
    assert "Do not add a finding, diagnosis or location the physician did not state" \
        in flat


def test_the_transcript_still_outranks_everything():
    assert tt.PRECEDENCE.index("The physician's transcript. Nothing overrides it.") \
        < tt.PRECEDENCE.index("THE EXAMINATION THAT WAS ACTUALLY PERFORMED")


def test_the_contrast_pointer_survived_the_rewrite():
    """RULES-NORMAL has to keep sending the model to the Contrast row in STUDY
    CONTEXT; that row exists because this rule refers to it."""
    assert "modality, regions, contrast" in tt.RULES_NORMAL
    assert "modality, regions, contrast" in _prompt()


def test_the_output_contract_is_untouched():
    got = _prompt()
    for key in ('"Report Title"', '"Pathological Findings"', '"Normal Findings"',
                '"Impression"', '"Recommendations"'):
        assert key in got, key


def test_no_normal_findings_content_was_invented_for_the_study_types():
    """The owner's point: no template library. `render_subtype_context` still emits
    technique / must_report / pathology only, and the HSG report came out correct
    anyway because the model was freed to use standard practice."""
    import io
    body = io.open(os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat",
                                "turbo_template.py"), encoding="utf-8-sig").read()
    seg = body[body.index("def render_subtype_context"):body.index("def render(*")]
    assert '"normal"' not in seg and "'normal'" not in seg


@pytest.mark.parametrize("modality,region", [
    ("CT", "brain"), ("MRI", "abdomen"), ("RADIOLOGY", "chest"),
    ("SONOGRAPHY", "abdomen"),
])
def test_the_advisory_rules_reach_every_modality(modality, region):
    got = tp.build_turbo_system_prompt(modality, "", profile={"regions": [region]})
    assert "THE REGIONAL CONTEXT IS GUIDANCE, NOT A SKELETON" in got
    assert "ADVISORY — one block per region" in got
