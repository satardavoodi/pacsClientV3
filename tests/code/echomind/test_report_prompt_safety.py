"""Guards for the report-generation PROMPT STACK (review of 2026-08-01).

These are clinical-safety guards, not style checks. Each one pins a defect that
was live in `openai_reporter.py` and would have reached a radiologist:

  * The radiography branch instructed the model to use "extreme exaggeration —
    vivid, dramatic phrasing" in a diagnostic report, and to invent pertinent
    negatives the physician never dictated.
  * Two of the three mammography few-shot examples assigned BI-RADS 1 to a
    breast for which the physician dictated no category at all.
  * MRI examples asserted "midline structures are preserved" alongside a
    documented midline shift, and wrote "presumed involved" under the heading
    "Normal Findings".
  * The temperature clamp and the output validator both keyed off a modality set
    that did not contain the strings the UI actually sends.

Worked examples dominate prose rules, so a wrong example is a wrong product.
"""
from __future__ import annotations

import os
import re

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_REPORTER = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "openai_reporter.py")

#: The exact values `ai_chat_widgets._modality_options` can produce.
_UI_MODALITIES = ("CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY")


def _src() -> str:
    with open(_REPORTER, encoding="utf-8") as fh:
        return fh.read()


def _code_only(text: str) -> str:
    """Drop whole-line Python comments so a guard never trips on the comment
    that documents the defect it guards against."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def _without_prohibitions(text: str) -> str:
    """Strip the rule blocks that must QUOTE a banned phrase in order to ban it.

    A guard has to search the prompt for "presumed involved"; the rule that
    forbids it also contains "presumed involved". Without this the guard trips
    on its own countermeasure — which is exactly the failure mode these guards
    exist to prevent, so it is worth doing properly rather than loosening the
    assertion.
    """
    out, skipping = [], False
    for line in text.splitlines():
        s = line.strip()
        if "NEVER-PRESUME RULE" in s:
            skipping = True
            continue
        if skipping:
            # the block ends at the next all-caps section header
            if s.startswith("ABSOLUTE PROHIBITIONS") or s.startswith("SELF-CHECK"):
                skipping = False
            else:
                continue
        if s.startswith("- NEVER") or s.startswith("• NEVER") or s.startswith("NEVER "):
            continue
        out.append(line)
    return "\n".join(out)


def _examples_section(text: str) -> str:
    """Only the few-shot EXAMPLES — not the reference tables.

    "1 – Negative" is a legitimate entry in the ACR BI-RADS category table; it
    is only a defect when it appears as an example's OUTPUT value for a breast
    the physician never categorised.
    """
    marker = "SECTION 9 — EXAMPLES"
    idx = text.find(marker)
    if idx == -1:
        return ""
    # Drop the counter-example's WRONG line: it must display the wrong value in
    # order to teach against it. Everything else in the section is a gold output.
    return "\n".join(
        l for l in text[idx:].splitlines() if not l.strip().startswith("WRONG")
    )


# ── 1. tone: a report is not creative writing ────────────────────────────────

@pytest.mark.parametrize("banned", [
    "extreme exaggeration",
    "vivid, dramatic",
    "dramatic phrasing",
])
def test_no_creative_writing_instruction_in_any_prompt(banned):
    """This was LIVE in the radiography branch, which fires for the UI value
    "RADIOLOGY" — and that branch also had no temperature clamp, so it was the
    highest-variance sampling in the product combined with an instruction to
    overstate."""
    assert banned.lower() not in _code_only(_src()).lower(), (
        f"a prompt instructs the model to {banned!r} — this is a diagnostic "
        f"radiology report, not creative writing"
    )


def test_radiography_specifies_a_neutral_register():
    src = _src()
    assert "Neutral, declarative, professional radiological register" in src, (
        "the radiography tone rule is gone; without it the branch has no "
        "instruction about register at all"
    )


# ── 2. no manufactured pertinent negatives ───────────────────────────────────

def test_no_branch_orders_the_model_to_invent_normal_findings():
    """The radiography branch used to say: include all relevant normal findings
    NOT MENTIONED in the original report, covering aspects beyond the
    pathological findings — i.e. assert observations the radiologist never made.
    On a plain film the projection often cannot support the negative."""
    code = _code_only(_src()).lower()
    for phrase in (
        "all relevant normal findings not mentioned in the original report",
        "always state at least several normal points",
    ):
        assert phrase not in code, (
            f"a prompt still orders the model to manufacture normal findings: {phrase!r}"
        )


def test_projection_limited_negatives_are_guarded():
    assert "cannot support" in _src(), (
        "the rule forbidding projection-unsupportable negatives (pneumothorax, "
        "free intraperitoneal air) is gone"
    )


# ── 3. BI-RADS is the physician's call, never the model's ────────────────────

def test_no_mammography_example_invents_a_birads_category():
    """Both defective examples assigned "1 – Negative" to a breast the physician
    had only called normal in passing. BI-RADS 1 is a screening-interval and
    management decision with medico-legal weight."""
    examples = _examples_section(_src())
    assert examples, "the mammography EXAMPLES section moved — re-anchor this guard"
    for bad in ('"1 – Negative"', '"1 - Negative"'):
        assert bad not in examples, (
            "a mammography EXAMPLE assigns BI-RADS 1 again — the model will copy "
            "it for any breast casually described as normal. (The category table "
            "may legitimately define category 1; an example may not assign it "
            "without a dictated category.)"
        )


def test_the_birads_counter_example_is_present():
    src = _src()
    assert "COUNTER-EXAMPLE" in src, "the BI-RADS counter-example is gone"
    assert 'CORRECT → "BI-RADS Category": { "Left Breast": "Not mentioned" }' in src


def test_mammography_examples_do_not_invent_an_axillary_assessment():
    """Example 1's input never mentions the axilla."""
    src = _src()
    assert '"Axillary Evaluation": "No abnormal axillary lymph nodes detected.",' not in src


# ── 4. never presume, never self-contradict ──────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "presumed involved",
    "presumed normal",
    "not separately mentioned, presumed",
])
def test_no_example_presumes_a_finding(phrase):
    assert phrase not in _without_prohibitions(_code_only(_src())), (
        f"an example writes {phrase!r} — that is an assertion the physician "
        f"never made, and one of them appeared under 'Normal Findings'"
    )


def test_the_never_presume_rule_is_stated():
    src = _src()
    assert "NEVER-PRESUME RULE" in src
    assert "OMITTED from Normal Findings" in src


def test_no_example_calls_the_midline_preserved(  ):
    """MRI Example 1 asserted midline shift and mass effect in Pathological
    Findings, then "Midline structures are preserved." under Normal Findings —
    in the same rendered report."""
    src = _src()
    if "midline shift" in src.lower():
        assert "Midline structures are preserved" not in src, (
            "an example states midline shift and midline preservation in one report"
        )


# ── 5. the clamp and the validator must cover what the UI sends ──────────────

@pytest.mark.parametrize("ui_value", _UI_MODALITIES)
def test_every_ui_modality_is_clamped_and_validated(ui_value):
    """`_VALIDATED_MODALITIES` gates temperature=0.1, max_tokens, AND the output
    validator. It held only the correctly-spelled "mammography", so the UI's
    "MAMOGRAPHY" (one "m") fell through — the modality with the strictest
    structured output ran unclamped and unchecked. "RADIOLOGY" was absent too."""
    from modules.EchoMind.viewer_chat.openai_reporter import _VALIDATED_MODALITIES
    assert ui_value.lower() in _VALIDATED_MODALITIES, (
        f"{ui_value!r} is a live UI modality but is not clamped/validated"
    )


def test_validation_is_not_gated_to_two_modalities():
    code = _code_only(_src())
    assert 'modality.lower() in ("mri", "ct")' not in code, (
        "output validation is gated back to MRI/CT — the mammography and "
        "obstetric key-set constants become dead code again"
    )
    assert "_report_validation_enabled()" in code


def test_validation_has_a_kill_switch():
    assert "AIPACS_ECHOMIND_REPORT_VALIDATION" in _src()


def test_mammography_validator_accepts_every_dispatch_spelling():
    """The dispatch branch accepts four spellings; the validator accepted one,
    so the UI's misspelling was validated against the generic 3-key set and its
    BI-RADS category was never required."""
    from modules.EchoMind.viewer_chat.openai_reporter import (
        _MAMMOGRAPHY_REQUIRED_KEYS, _validate_report_json,
    )
    assert "BI-RADS Category" in _MAMMOGRAPHY_REQUIRED_KEYS
    good = (
        '{"Report Title":"t","Breast Composition":"c","Pathological Findings":"p",'
        '"Normal Findings":"n","Axillary Evaluation":"a","BI-RADS Category":"2"}'
    )
    missing = (
        '{"Report Title":"t","Breast Composition":"c","Pathological Findings":"p",'
        '"Normal Findings":"n","Axillary Evaluation":"a"}'
    )
    for spelling in ("mammography", "mamography", "mammogram", "mamogram"):
        _validate_report_json(good, spelling)          # must not raise
        with pytest.raises(ValueError):
            _validate_report_json(missing, spelling)   # must catch the missing BI-RADS


# ── 6. correction must not reshape the report ────────────────────────────────

def test_correction_mirrors_the_original_key_set():
    """`correction()` hard-coded a 5-key schema for every report. A mammography
    report has six different keys and an obstetric one eleven, so correcting a
    typo silently deleted the BI-RADS category, the breast composition and every
    obstetric section — and invented an empty Impression in their place."""
    code = _code_only(_src())
    assert "Output MUST contain EXACTLY these 5 keys" not in code, (
        "the correction prompt is back to a fixed 5-key schema"
    )
    assert "KEY-SET MIRROR" in code
    assert "the SAME top-level keys as ORIGINAL_REPORT" in code


def test_correction_forbids_narration_keys():
    src = _src()
    assert '"Changes Made"' in src, "the no-narration rule is gone from the correction prompt"


def test_correction_pins_the_output_language():
    src = _src()
    assert "Persian in, Persian out" in src, (
        "the correction prompt has no language lock; a Persian report can come "
        "back part-English"
    )
