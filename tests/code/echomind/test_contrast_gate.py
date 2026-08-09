"""Guard: contrast is a real gate axis, not a rule pointing at an empty field.

OBSERVED 2026-08-09, patient 53696. Booked «سی تی اسکن اسپیرال مغز بدون تزریق» — a
brain CT explicitly WITHOUT contrast. The prompt that went out contained, at once:

  * five normal-findings lines describing enhancement ("No abnormal parenchymal,
    leptomeningeal, or dural enhancement", "Choroid plexuses enhance symmetrically",
    and three more), and
  * two rules forbidding exactly that — "Without it, say nothing about enhancement —
    that is a fabricated observation" and "Do not describe enhancement on a
    non-contrast study, even to deny it".

And `RULES — NORMAL FINDINGS` step 1 said "Take the examination from STUDY CONTEXT:
modality, regions, contrast" while STUDY CONTEXT rendered **no Contrast row at all**:
`case.contrast` was read by the gate profile but nothing had ever populated it.

The model got it right — it read «بدون تزریق» out of the Persian Service string and
suppressed all five lines. But the same prompt showed REPORTING CONTEXT beating RULES
on attenuation-vs-density (the model wrote "hyperdensity" where `# MODALITY — CT`, a
higher-precedence slot, said to use attenuation). A fabrication safeguard that depends
on precedence running the other way is not one to keep.

So: detect the contrast state, render it, and remove the contradiction at the source.
Unknown contrast must change nothing — guessing would delete real guidance.
"""

import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind import session_metadata as sm                     # noqa: E402
from modules.EchoMind.viewer_chat import turbo_prompt as tp             # noqa: E402
from modules.EchoMind.viewer_chat import turbo_template as tt           # noqa: E402

BRAIN = {"regions": ["brain"]}


def _p(contrast="", **over):
    prof = dict(BRAIN)
    prof["contrast"] = contrast
    prof.update(over)
    return tp.build_turbo_system_prompt("CT", "", profile=prof)


def _normal_block(prompt):
    seg = prompt.split("Normal-findings reference", 1)[1]
    for stop in ("Dictation terms", "  Notes", "# OUTPUT"):
        if stop in seg:
            seg = seg.split(stop, 1)[0]
    return seg


# ── detection ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("سی تی اسکن اسپیرال مغز بدون تزریق", "without"),   # the real 53696 booking
    ("سی تی اسکن شکم و لگن با تزریق", "with"),
    ("ام آر آی مغز بدون ماده حاجب", "without"),
    ("سی تی آنژیوگرافی با ماده حاجب", "with"),
    ("CT brain non-contrast", "without"),
    ("CT chest without contrast", "without"),
    ("CT abdomen with contrast", "with"),
    ("MRI post-contrast", "with"),
    ("unenhanced CT of the abdomen", "without"),
])
def test_the_booking_text_is_read(text, expected):
    assert sm.detect_contrast(text)[0] == expected


@pytest.mark.parametrize("text,expected", [
    ("MRI شکم بدون مواد حاجب", "without"),   # «مواد» plural — the booked form
    ("MRI شکم بدون ماده حاجب", "without"),   # «ماده» singular
    ("MRI دینامیک هر قسمت بدن", "with"),      # a dynamic protocol IS a contrast one
    ("ام آر آی تری فازیک کبد", "with"),
    ("MRI liver triphasic", "with"),
])
def test_the_forms_patient_52230_exposed(text, expected):
    """Only the singular «ماده» was listed, so the plural — the form reception actually
    books with — detected nothing at all."""
    assert sm.detect_contrast(text)[0] == expected


def test_a_booking_that_says_both_things_says_nothing():
    """THE 52230 CASE. Two services in one string:

        «MRI دینامیک هر قسمت بدن بجز قلب / MRI ... شکم بدون مواد حاجب»

    one implying contrast, one excluding it. The study was in fact triphasic
    post-contrast. Resolving to 'without' here would strip the enhancement
    normal-lines off a contrast-enhanced study — worse than the original miss.
    """
    booking = ("MRI دینامیک هر قسمت بدن بجز قلب / "
               "MRI (به عنوان مثال proton) شکم بدون مواد حاجب")
    assert sm.detect_contrast(booking) == ("", "conflict")


# ── "with and without" is a contrast study, not a conflict ───────────────

@pytest.mark.parametrize("text", [
    "MRI مغز با و بدون ماده حاجب",
    "MRI مغز با و بدون ماده حاجب / MRI سرویکال با و بدون ماده حاجب",
    "MRI brain with and without contrast",
    "CT قبل و بعد از تزریق",
    "pre and post contrast MRI",
])
def test_with_and_without_means_contrast_was_given(text):
    """OBSERVED, patient 52057. «با و بدون ماده حاجب» contains «بدون ماده حاجب»
    verbatim, so an MS protocol that HAD been injected was recorded as non-contrast and
    100 characters of enhancement normal-lines were stripped out of its prompt.

    It is also not a conflict: a with-and-without study is one study that was injected,
    and the enhancement guidance applies to it."""
    assert sm.detect_contrast(text)[0] == "with", text


def test_with_and_without_keeps_the_enhancement_lines():
    state, _ = sm.detect_contrast("MRI مغز با و بدون ماده حاجب")
    block = _normal_block(_p(state))
    assert any("enhanc" in l.lower() for l in block.splitlines()), \
        "a with-and-without study lost its enhancement normal-lines"


def test_plain_without_is_not_swallowed_by_the_both_form():
    """The new rule must not turn every non-contrast study into a contrast one."""
    assert sm.detect_contrast("MRI مغز بدون ماده حاجب")[0] == "without"
    assert sm.detect_contrast("سی تی اسکن اسپیرال مغز بدون تزریق")[0] == "without"
    assert sm.detect_contrast("CT brain non-contrast")[0] == "without"


def test_a_conflict_across_separate_fields_is_still_a_conflict():
    """first-match-wins used to hide this: the booking and the study description are
    two arguments, and disagreement between them is exactly as ambiguous."""
    assert sm.detect_contrast("CT abdomen without contrast",
                              "CT ABDOMEN DYNAMIC") == ("", "conflict")


def test_a_conflict_filters_nothing():
    """The whole point. Ambiguous must behave exactly like unknown."""
    state, _ = sm.detect_contrast("MRI دینامیک / MRI شکم بدون مواد حاجب")
    prof = {"regions": ["abdomen"], "contrast": state}
    got = tp.build_turbo_system_prompt("MRI", "", profile=prof)
    assert got == tp.build_turbo_system_prompt("MRI", "",
                                               profile={"regions": ["abdomen"]})


@pytest.mark.parametrize("text", [
    "سی تی اسکن مغز", "CT brain", "Head Helical", "", None, "   ",
])
def test_silence_stays_unknown(text):
    """Unknown is a first-class answer. A guess either deletes real guidance or
    licenses a fabricated observation."""
    assert sm.detect_contrast(text)[0] == ""


def test_arabic_and_persian_script_both_match():
    """Reception staff type on mixed keyboards, so the same word arrives with Arabic
    ي/ك or Persian ی/ک. Matching one and silently missing the other is the kind of
    bug nobody reports because it just looks like detection not working sometimes."""
    persian = sm.detect_contrast("سی تی اسکن مغز بدون تزریق")[0]
    arabic = sm.detect_contrast("سي تي اسكن مغز بدون تزريق")[0]
    assert persian == arabic == "without"


def test_without_is_never_read_as_with():
    """«بدون تزریق» CONTAINS «تزریق». A with-first match order would invert every
    non-contrast study in the clinic into a contrast one."""
    for t in ("بدون تزریق", "مغز بدون تزریق", "بدون ماده حاجب", "بدون کنتراست"):
        assert sm.detect_contrast(t)[0] == "without", t


def test_the_zero_width_non_joiner_does_not_break_matching():
    assert sm.detect_contrast("سی تی اسکن مغز بدون‌تزریق")[0] == "without"


@pytest.mark.parametrize("agent,expected", [
    ("OMNIPAQUE", "with"), ("Ultravist 370", "with"),
    ("", ""), ("NONE", ""), ("none", ""), ("N/A", ""), ("-", ""), ("0", ""),
])
def test_the_dicom_agent_tag_is_one_vote_not_gospel(agent, expected):
    """Scanners routinely populate ContrastBolusAgent with NONE or a blank."""
    assert sm.detect_contrast("", agent=agent)[0] == expected


def test_the_booking_wins_when_the_agent_tag_is_junk():
    assert sm.detect_contrast("مغز بدون تزریق", agent="NONE") == ("without", "service_text")


def test_a_real_agent_outranks_the_booking():
    """The tag records what was administered; the booking records what was ordered."""
    assert sm.detect_contrast("brain CT", agent="OMNIPAQUE") == ("with", "dicom")


def test_the_dicom_tag_is_actually_collected():
    src = open(os.path.join(_ROOT, "modules", "EchoMind", "session_metadata.py"),
               encoding="utf-8-sig").read()
    assert '"ContrastBolusAgent"' in src, "detect_contrast can never see an agent"
    assert 'rec["case"]["contrast"]' in src, "case.contrast is still never populated"


# ── the Contrast row exists, so the rule points at something ─────────────────

def test_the_rule_that_sends_the_model_to_study_context_is_still_there():
    assert "modality, regions, contrast" in _p("without")


@pytest.mark.parametrize("state,probe", [
    ("without", "without contrast"),
    ("with", "with contrast"),
])
def test_the_contrast_row_renders_when_known(state, probe):
    rows = [l for l in _p(state).splitlines() if l.strip().startswith("Contrast   ")]
    assert rows, f"no Contrast row for {state!r}"
    assert probe in rows[0]


def test_no_contrast_row_when_unknown():
    """An empty row would be worse than none: it reads as a field the model should
    have been given and wasn't."""
    assert not [l for l in _p("").splitlines() if l.strip().startswith("Contrast   ")]


# ── the contradiction is gone ────────────────────────────────────────────────

def test_a_non_contrast_study_gets_no_enhancement_normal_lines():
    block = _normal_block(_p("without"))
    offenders = [l.strip() for l in block.splitlines() if "enhanc" in l.lower()]
    assert not offenders, f"still shipping enhancement lines: {offenders}"


def test_a_contrast_study_keeps_them():
    block = _normal_block(_p("with"))
    assert any("enhanc" in l.lower() for l in block.splitlines())


def test_unknown_contrast_changes_absolutely_nothing():
    """The whole design rests on this: only a POSITIVE 'no contrast' filters."""
    assert _p("") == tp.build_turbo_system_prompt("CT", "", profile=dict(BRAIN))


def test_the_non_contrast_prompt_is_shorter_but_not_gutted():
    without, unknown = _p("without"), _p("")
    assert len(without) < len(unknown)
    assert len(_normal_block(without).strip().splitlines()) >= 10, \
        "the brain normal reference lost too much"


@pytest.mark.parametrize("state", ["without", "with", ""])
def test_the_prose_rule_survives_every_state(state):
    """Belt and braces. Removing the lines does not remove the reason."""
    assert "say nothing about enhancement" in _p(state)


@pytest.mark.parametrize("modality,region", [
    ("CT", "brain"), ("CT", "abdomen"), ("MRI", "brain"), ("MRI", "abdomen"),
])
def test_the_filter_is_not_brain_ct_only(modality, region):
    prof = {"regions": [region], "contrast": "without"}
    block = _normal_block(tp.build_turbo_system_prompt(modality, "", profile=prof))
    assert not [l for l in block.splitlines() if "enhanc" in l.lower()], \
        f"{modality}/{region} still carries enhancement lines"


# ── the safety rails on the filter itself ────────────────────────────────────

def test_a_region_is_never_left_with_no_normal_guidance():
    """A block carrying a contradiction is bad; a block with no normal findings
    reference at all is a silent, total loss of coverage for that region."""
    allenh = {"title": "Synthetic", "headings": "A · B",
              "normal": ["No abnormal enhancement.", "Vessels enhance normally."],
              "pathology": [], "terms": [], "notes": []}
    out = tt.render_region_context([allenh], contrast="without")
    assert "No abnormal enhancement." in out, "the reference was emptied"


def test_the_filter_keeps_the_lines_it_should():
    keep = "Grey-white matter differentiation is preserved bilaterally."
    drop = "No abnormal parenchymal, leptomeningeal, or dural enhancement."
    mod = {"title": "T", "headings": "A", "normal": [keep, drop],
           "pathology": [], "terms": [], "notes": []}
    out = tt.render_region_context([mod], contrast="without")
    assert keep in out and drop not in out


@pytest.mark.parametrize("state", ["without", "none", "non-contrast", "NONCONTRAST",
                                   "unenhanced", "  Without  "])
def test_every_absent_spelling_filters(state):
    mod = {"title": "T", "headings": "A", "pathology": [], "terms": [], "notes": [],
           "normal": ["Plain line.", "No abnormal enhancement."]}
    out = tt.render_region_context([mod], contrast=state)
    assert "No abnormal enhancement." not in out, state


@pytest.mark.parametrize("state", ["with", "", "unknown", "iv", None])
def test_no_other_value_filters(state):
    mod = {"title": "T", "headings": "A", "pathology": [], "terms": [], "notes": [],
           "normal": ["Plain line.", "No abnormal enhancement."]}
    out = tt.render_region_context([mod], contrast=state)
    assert "No abnormal enhancement." in out, state


def test_the_drop_is_logged_rather_than_silent(caplog):
    """No silent caps: a prompt that quietly lost five lines must say so."""
    mod = {"title": "Brain", "headings": "A", "pathology": [], "terms": [], "notes": [],
           "normal": ["Plain line.", "No abnormal enhancement."]}
    with caplog.at_level("INFO",
                         logger="modules.EchoMind.viewer_chat.turbo_template"):
        tt.render_region_context([mod], contrast="without")
    blob = " ".join(r.getMessage() for r in caplog.records)
    assert "contrast-dependent normal line" in blob and "Brain" in blob


def test_the_v1_narrowing_path_still_understands_the_canonical_value():
    """`detect_contrast` emits 'without'; the pre-template path matches on that word
    to drop its BRAIN CT WITH CONTRAST block. The two must not drift."""
    src = open(os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat",
                            "turbo_prompt.py"), encoding="utf-8-sig").read()
    a = src.index("# Contrast refines brain")
    # To the end of the statement, not a guessed character count: the accepted-value
    # tuple is line-wrapped, so a fixed window silently cuts it in half.
    seg = src[a:src.index("BRAIN CT WITH CONTRAST", a)]
    for accepted in ('"without"', '"none"', '"non-contrast"'):
        assert accepted in seg, f"the v1 path no longer accepts {accepted}"
    assert sm.detect_contrast("مغز بدون تزریق")[0] == "without", \
        "detect_contrast emits a value the v1 narrowing path does not recognise"
