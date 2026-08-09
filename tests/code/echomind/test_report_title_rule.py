"""Guard: the report title follows the physician, not the scanner (2026-08-09).

OBSERVED. Patient 52230, 19:48. The physician opened with

    «ام آر آی از ناحیه شکم به صورت تری فازیک شماره ۱ بنویس»
     an MRI of the ABDOMEN region, triphasic, number 1

and the report came back titled **"Triphasic MRI of the Abdomen and Pelvis"**.

"and Pelvis" came from the STUDY CONTEXT `Regions` row, which is DICOM-derived
(`BodyPartExamined = ABDOMEN, ABDOMENPELVIS`). The model took "Triphasic" from the
transcript and the region from the scanner — mixing its two sources inside one field.

The cause was simple: `"Report Title": string` in the OUTPUT schema was the ONLY
mention of the title anywhere in the 11,312-character prompt. There was no rule at
all, so there was nothing for PRECEDENCE rule 1 ("The physician's transcript. Nothing
overrides it.") to act on. The title is the first claim a report makes about what was
examined, and it was the one field left unspecified.
"""

import os
import re
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind.viewer_chat import turbo_prompt as tp             # noqa: E402
from modules.EchoMind.viewer_chat import turbo_template as tt           # noqa: E402

_ABDO = {"regions": ["abdomen", "pelvis"]}


# ── the rule exists ──────────────────────────────────────────────────────────

def test_the_title_has_a_rule_at_all():
    """It had none. That is the whole bug."""
    assert '"Report Title" names the examination' in tt.OUTPUT


@pytest.mark.parametrize("probe", [
    "modality", "technique", "region",
    "Take the region from the PHYSICIAN",
    "Never widen the title to a region he did not name",
])
def test_the_rule_says_what_the_title_is_made_of(probe):
    assert probe in tt.OUTPUT, f"missing: {probe}"


def test_the_rule_names_its_fallbacks_in_precedence_order():
    """Transcript, then the booking, then the scanner — the same ladder PRECEDENCE
    already declares for everything else."""
    seg = tt.OUTPUT[tt.OUTPUT.index('"Report Title" names'):]
    seg = seg[:seg.index("Inside the string values")]
    assert seg.index("PHYSICIAN") < seg.index("Service") < seg.index("STUDY CONTEXT")


def test_the_observed_case_is_recorded_in_the_rule():
    """The example is the actual dictation, so the next reader can see what it fixed."""
    assert "تری فازیک" in tt.OUTPUT
    assert "triphasic MRI of the abdomen" in tt.OUTPUT


# ── it reaches every modality ────────────────────────────────────────────────

@pytest.mark.parametrize("modality,region", [
    ("CT", "brain"), ("MRI", "abdomen"), ("RADIOLOGY", "chest"),
    ("SONOGRAPHY", "abdomen"),
])
def test_the_rule_reaches_the_rendered_prompt(modality, region):
    got = tp.build_turbo_system_prompt(modality, "", profile={"regions": [region]})
    assert '"Report Title" names the examination' in got


def test_mammography_is_unaffected():
    """Mammography is prefix-gated onto a regex-locked schema whose title contract is
    defined elsewhere. The template's OUTPUT slot never reaches it."""
    from modules.EchoMind.viewer_chat.openai_reporter import (
        build_report_system_prompt as shared)
    got = tp.build_turbo_system_prompt("MAMOGRAPHY", "", profile={"regions": ["breast"]})
    assert got.endswith(shared("MAMOGRAPHY", ""))
    assert '"Report Title" names the examination' not in got


# ── and it does not disturb the contract around it ───────────────────────────

def test_the_json_schema_is_untouched():
    for key in ('"Report Title":', '"Pathological Findings":', '"Normal Findings":',
                '"Impression":', '"Recommendations":'):
        assert key in tt.OUTPUT, key
    assert tt.OUTPUT.rstrip().endswith("Start with { and end with }.")


def test_the_heading_rule_still_follows_the_title_rule():
    """The title paragraph was inserted ahead of the heading paragraph; both must
    survive, in that order."""
    a = tt.OUTPUT.index('"Report Title" names the examination')
    b = tt.OUTPUT.index("Inside the string values")
    c = tt.OUTPUT.index("a heading is a claim that the")
    assert a < b < c


def test_the_rule_does_not_redefine_the_output_shape():
    seg = tt.OUTPUT[tt.OUTPUT.index('"Report Title" names'):]
    seg = seg[:seg.index("Inside the string values")]
    for leak in ("json", "{", "}", "null"):
        assert leak not in seg.lower(), f"the title rule is restating the schema: {leak}"


def test_the_prompt_grew_by_only_the_rule():
    """A title rule should cost a paragraph, not reshape the prompt."""
    got = tp.build_turbo_system_prompt("MRI", "", profile=_ABDO)
    assert 400 < len(tt.OUTPUT) - 587 < 900, \
        "the OUTPUT slot changed by an unexpected amount"
    assert got.count("# OUTPUT") == 1
