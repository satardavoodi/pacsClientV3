"""Guard: a two-region study reports both, and can be corrected (2026-08-11).

OBSERVED. Patient 54120, booked

    «راديوگرافي پاشنه پاي چپ دو نما / راديوگرافي زانوي چپ نماي (AP) و (Lateral)»
     LEFT HEEL, two views  /  LEFT KNEE, AP and lateral

The gate produced `regions=['knee']`. Four defects, each independently sufficient:

1. THE HEEL HAD NO VOCABULARY. «پاشنه», «کالکانوس», "calcaneus", "heel" matched
   nothing, and CALCANEUS/HEEL were missing from the DICOM map too.

2. A PARTIAL PARSE REPLACED THE WHOLE SET. Two segments, one understood. Because the
   booking outranks DICOM, the half we understood REPLACED the region set — failing to
   read half a booking silently deleted the other half.

3. THE CORRECTION FRAME FORBADE THE FIX. He asked twice for calcaneus normal findings.
   The frame said "Do not regenerate Normal Findings", so the model deleted the knee
   normals and emitted the literal "Normal findings knee."

4. THE CORRECTION HAD NO REGION CONTEXT AT ALL, so it had nothing to write calcaneus
   normals from even had it been allowed.

Also from the same log: `regions ['brain','temporal_bone'] -> ['temporal_bone']`
narrowed into a region radiography has no package for, giving ctx=0 and the full
35 754-char ungated prompt. Narrowing that destroys the gate is worse than none.
"""

import io
import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind import session_metadata as sm                     # noqa: E402
from modules.EchoMind.viewer_chat import turbo_modules as tm            # noqa: E402
from modules.EchoMind.viewer_chat import turbo_prompt as tp             # noqa: E402

_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")

SERVICE_54120 = ("راديوگرافي پاشنه پاي چپ دو نما / "
                 "راديوگرافي زانوي چپ نماي (AP) و (Lateral) - ايستاده")


# ── 1. the heel exists ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "پاشنه", "پاشنه پا", "پاشنه پای چپ", "کالکانوس", "کالکانئوس",
    "calcaneus", "calcaneum", "heel",
])
def test_the_heel_resolves_to_ankle_foot(text):
    assert sm.detect_regions_from_text(text) == ("ankle_foot",)


@pytest.mark.parametrize("tag", ["CALCANEUS", "CALCANEUM", "HEEL"])
def test_the_dicom_map_knows_the_heel(tag):
    assert sm.normalize_region(tag) == ("ankle_foot",)


def test_the_54120_booking_yields_both_regions():
    got = sm.detect_regions_from_text(SERVICE_54120)
    assert set(got) == {"ankle_foot", "knee"}, got


def test_the_order_follows_the_booking():
    """The heel is named first, so it reports first."""
    assert sm.detect_regions_from_text(SERVICE_54120)[0] == "ankle_foot"


def test_both_blocks_render():
    prof = {"regions": list(sm.detect_regions_from_text(SERVICE_54120))}
    got = tp.build_turbo_system_prompt("RADIOLOGY", "", profile=prof)
    blocks = [l.strip() for l in got.splitlines() if l.startswith("## ")]
    assert blocks == ["## Ankle and foot", "## Knee"], blocks


# ── 2. a partial parse must not narrow ───────────────────────────────────────

def test_a_fully_understood_booking_is_complete():
    assert sm.regions_from_text_complete(SERVICE_54120) is True


def test_a_half_understood_booking_is_not_complete():
    """This is the flag that stops the understood half deleting the rest."""
    assert sm.regions_from_text_complete(
        "راديوگرافي يک چيز ناشناخته / راديوگرافي زانو") is False


def test_segments_split_on_the_separators_a_booking_uses():
    segs = sm._service_segments(SERVICE_54120)
    assert len(segs) == 2
    assert any("پاشنه" in s for s in segs) and any("زانو" in s for s in segs)


def test_an_incomplete_booking_unions_rather_than_replaces():
    src = io.open(os.path.join(_ROOT, "modules", "EchoMind", "session_metadata.py"),
                  encoding="utf-8-sig").read()
    body = src[src.index("_svc_complete"):src.index('rec["provenance"] = prov')]
    assert "dicom+service_partial" in body
    assert "only partly understood" in body


# ── 3 + 4. the correction can add what he asked for ──────────────────────────

def test_the_frame_no_longer_bans_regenerating_normals():
    frame = tp.TURBO_CORRECTION_FRAME
    assert "Do not regenerate Normal Findings." not in frame, \
        "this is the line that made his correction impossible"


@pytest.mark.parametrize("probe", [
    "add, extend, split or restructure",
    "Never\n  answer such a request by deleting the normals you already had",
    'Normal findings knee.',
])
def test_the_frame_permits_and_bounds_the_addition(probe):
    assert probe in tp.TURBO_CORRECTION_FRAME, probe


def test_unmentioned_normals_are_still_protected():
    """Permission to add must not become permission to rewrite everything."""
    assert "Do not rewrite Normal Findings that the request did not mention" \
        in tp.TURBO_CORRECTION_FRAME


def test_the_correction_carries_the_region_context():
    pre = tp.build_turbo_correction_prefix(
        {"regions": ["ankle_foot", "knee"], "modality": "RADIOLOGY", "contrast": ""})
    assert "EDIT, DO NOT GENERATE" in pre
    assert "# REPORTING CONTEXT" in pre
    assert "## Ankle and foot" in pre and "## Knee" in pre


def test_the_correction_context_really_resolves():
    """The imports it needs are function-local; a NameError here would be swallowed by
    the surrounding except and silently return the bare frame, with every test green.
    So assert the block is actually present, not merely that the code path ran."""
    bare = tp.build_turbo_correction_prefix()
    withctx = tp.build_turbo_correction_prefix(
        {"regions": ["knee"], "modality": "RADIOLOGY"})
    assert len(withctx) > len(bare) + 500


def test_no_profile_still_returns_the_plain_frame():
    assert tp.build_turbo_correction_prefix() == tp.TURBO_CORRECTION_FRAME


def test_an_unknown_modality_degrades_to_the_plain_frame():
    got = tp.build_turbo_correction_prefix(
        {"regions": ["knee"], "modality": "NOT_A_MODALITY"})
    assert got == tp.TURBO_CORRECTION_FRAME


def test_the_correction_profile_ignores_the_note():
    """The correction note is an instruction, not a dictation. Mining it for regions
    would let the words of the edit redefine the study."""
    s = io.open(_PAGES, encoding="utf-8-sig").read()
    a = s.index("    def _correction_gate_profile(self):")
    body = s[a:s.index("\n    def ", a + 50)]
    assert "self._build_gate_profile()" in body
    assert "note" not in body.split('"""')[2]


def test_the_correction_passes_the_profile():
    s = io.open(_PAGES, encoding="utf-8-sig").read()
    assert "build_turbo_correction_prefix(self._correction_gate_profile())" in s


# ── the multi-body-part output shape (owner's format, 2026-08-11) ─────────

def _flat(s):
    return " ".join(str(s).split())


def test_a_multi_part_study_is_organised_by_body_part_first():
    """His format: everything about the knee in one place, everything about the
    calcaneus in another — not two sections the reader has to cross-reference."""
    from modules.EchoMind.viewer_chat import turbo_template as tt
    flat = _flat(tt.OUTPUT)
    assert "WHEN THE STUDY COVERS MORE THAN ONE BODY PART" in tt.OUTPUT
    assert "by body part FIRST, anatomy second" in flat


def test_the_two_keys_must_agree_on_names_and_order():
    """Without this the two halves cannot be read together, and a later renderer
    could not pair them."""
    from modules.EchoMind.viewer_chat import turbo_template as tt
    flat = _flat(tt.OUTPUT)
    assert "named the same way and in the same order in both keys" in flat


def test_a_normal_body_part_still_gets_a_pathology_line():
    """54120's knee was normal and simply absent from Pathological Findings, which
    reads as a body part nobody looked at."""
    from modules.EchoMind.viewer_chat import turbo_template as tt
    flat = _flat(tt.OUTPUT)
    assert "Every body part the study covered appears in BOTH keys" in flat
    assert "reads as one that was never examined" in flat


def test_the_rule_reaches_a_multi_region_prompt():
    prof = {"regions": list(sm.detect_regions_from_text(SERVICE_54120))}
    got = tp.build_turbo_system_prompt("RADIOLOGY", "", profile=prof)
    assert "WHEN THE STUDY COVERS MORE THAN ONE BODY PART" in got


# ── it has to hold for EVERY modality that can be multi-region ────────────

#: The four the nine-slot template renders. MAMOGRAPHY is deliberately absent — see
#: `test_mammography_is_multi_part_by_schema_instead`.
_TEMPLATE_MODALITIES = ("CT", "MRI", "RADIOLOGY", "SONOGRAPHY")

_MULTI = [
    ("CT", ["chest", "abdomen"]),
    ("CT", ["abdomen", "pelvis"]),
    ("CT", ["chest", "abdomen", "pelvis"]),
    ("CT", ["brain", "paranasal_sinuses"]),
    ("MRI", ["abdomen", "pelvis"]),
    ("MRI", ["brain", "spine_cervical"]),
    ("MRI", ["spine_lumbar", "knee"]),
    ("RADIOLOGY", ["knee", "ankle_foot"]),
    ("RADIOLOGY", ["chest", "abdomen"]),
    ("RADIOLOGY", ["wrist_hand", "elbow"]),
    ("SONOGRAPHY", ["abdomen", "pelvis"]),
    ("SONOGRAPHY", ["abdomen", "scrotum"]),
]


@pytest.mark.parametrize("modality,regions", _MULTI)
def test_every_multi_region_combination_gets_the_rule(modality, regions):
    got = tp.build_turbo_system_prompt(modality, "", profile={"regions": regions})
    assert "WHEN THE STUDY COVERS MORE THAN ONE BODY PART" in got, (modality, regions)


@pytest.mark.parametrize("modality,regions", _MULTI)
def test_every_multi_region_combination_renders_every_block(modality, regions):
    """The rule is useless if the anatomy it asks the model to group by never arrived."""
    got = tp.build_turbo_system_prompt(modality, "", profile={"regions": regions})
    blocks = [l.strip()[3:] for l in got.splitlines() if l.startswith("## ")]
    expected = len({m["title"] for m in tm.modules_for(modality, regions)})
    assert len(blocks) == expected == len(regions), (modality, regions, blocks)


@pytest.mark.parametrize("modality", _TEMPLATE_MODALITIES)
def test_a_single_region_study_is_unharmed(modality):
    """The rule is conditional prose, so it ships on every study. It must not make a
    one-part report grow a body-part heading it does not need."""
    got = tp.build_turbo_system_prompt(modality, "", profile={"regions": ["abdomen"]})
    assert "WHEN THE STUDY COVERS MORE THAN ONE BODY PART" in got
    assert got.count("# OUTPUT") == 1


def test_two_regions_sharing_one_package_is_deduplication_not_loss():
    """Ultrasound maps both `thyroid` and `head_neck` to the single `Neck` package, so
    that pair renders ONE block. Recorded because a coverage sweep reads it as a lost
    region and the next person will chase it."""
    titles = {m["title"] for m in tm.modules_for("SONOGRAPHY", ["thyroid", "head_neck"])}
    assert titles == {"Neck"}
    assert {m["title"] for m in tm.modules_for("SONOGRAPHY", ["thyroid"])} == titles


def test_mammography_is_multi_part_by_schema_instead():
    """MAMOGRAPHY never sees the template's OUTPUT slot — it is a PREFIX onto a
    regex-locked schema. It does not need the rule: that schema is already per-side,
    with separate Right Breast and Left Breast entries. Asserted so "all modalities"
    has a documented answer rather than an assumed one."""
    from modules.EchoMind.viewer_chat.openai_reporter import (
        build_report_system_prompt as shared)
    got = tp.build_turbo_system_prompt("MAMOGRAPHY", "", profile={"regions": ["breast"]})
    assert "WHEN THE STUDY COVERS MORE THAN ONE BODY PART" not in got
    mg = shared("MAMOGRAPHY", "")
    assert "Right Breast" in mg and "Left Breast" in mg


def test_the_kill_switch_removes_it_with_the_rest_of_the_template(monkeypatch):
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "0")
    got = tp.build_turbo_system_prompt("CT", "",
                                       profile={"regions": ["abdomen", "pelvis"]})
    assert "WHEN THE STUDY COVERS MORE THAN ONE BODY PART" not in got


def test_the_output_contract_is_unchanged():
    """The five keys are parsed, validated, stored and exported. The body-part shape
    lives INSIDE the string values and must never become new keys."""
    from modules.EchoMind.viewer_chat import turbo_template as tt
    for key in ('"Report Title"', '"Pathological Findings"', '"Normal Findings"',
                '"Impression"', '"Recommendations"'):
        assert key in tt.OUTPUT, key
    assert tt.OUTPUT.rstrip().endswith("Start with { and end with }.")


# ── narrowing may not destroy the gate ─────────────────────────────────

def test_radiography_really_has_no_temporal_bone_package():
    """The precondition for the bug. If a package is added later this test tells the
    next reader why the guard below exists rather than leaving it mysterious."""
    assert not tm.modules_for("RADIOLOGY", ["temporal_bone"])
    assert tm.modules_for("RADIOLOGY", ["brain"])


def test_narrowing_is_refused_when_it_would_lose_the_gate():
    s = io.open(_PAGES, encoding="utf-8-sig").read()
    a = s.index("    def _build_gate_profile(self")
    body = s[a:s.index("\n    def ", a + 50)]
    assert "keeps_gate" in body
    assert "the gate would be lost" in body
    assert "_mods_for" in body


def test_narrowing_still_happens_when_the_gate_survives():
    """The guard must not disable narrowing altogether — 52057 and 52230 depend on it."""
    s = io.open(_PAGES, encoding="utf-8-sig").read()
    a = s.index("    def _build_gate_profile(self")
    body = s[a:s.index("\n    def ", a + 50)]
    assert "narrowed by the dictation" in body
    assert "regions = spoken" in body


def test_the_observed_case_is_recorded_where_the_fixes_live():
    meta = io.open(os.path.join(_ROOT, "modules", "EchoMind", "session_metadata.py"),
                   encoding="utf-8-sig").read()
    assert "54120" in meta
    pages = io.open(_PAGES, encoding="utf-8-sig").read()
    assert "temporal_bone" in pages
