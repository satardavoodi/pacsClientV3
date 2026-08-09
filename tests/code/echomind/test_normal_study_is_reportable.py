"""Guard: a completely normal study is a valid report (2026-08-08).

THE CASE THAT CAUSED THIS. Patient 53587, 2026-08-08 13:07. The physician dictated a
normal brain CT — «نرمال نرمال بزن». The model did the right thing and returned an
EMPTY 'Pathological Findings', because there are none. The validator then threw the
entire report away:

    ValueError: Required key missing or empty: 'Pathological Findings'

Twice — 27 s and 16 s of model time — and the physician gave up and moved to the next
patient. A completely normal study is one of the commonest reports in radiology, and it
was unreportable.

The fix has to hold BOTH edges at once, which is what these tests pin:
  * a PRESENT-but-empty field means "nothing abnormal" and must be accepted;
  * an ABSENT key still means truncated/garbled JSON and must still raise. Relaxing
    that too would trade a visible failure for a silently half-empty report.

THE MIRROR CASE (2026-08-09). Patient 53673, chest CT, 18:30. The dictation ended
«همینایی که گفتم بزن دیگه» — "write only the ones I said". The model complied and
returned an empty 'Normal Findings'; the validator threw the whole report away with

    ValueError: Required key missing or empty: 'Normal Findings'

This file previously asserted the opposite — "a report with no normal findings is a
broken response" — which was a reasonable belief until a physician asked for exactly
that. 'Normal Findings' is now NULLABLE for the plain-string modalities.

The asymmetry with pathology is deliberate and is itself pinned below: an empty
pathology field is replaced with a SENTENCE, an empty normals field is replaced with
NULL. "No pathological findings are identified" is a safe default; there is no safe
default sentence for normals, because any text there asserts that structures were
examined and found normal when the physician never said so.
"""

import ast
import json
import os
import re
import sys
import typing

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
_REP = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "openai_reporter.py")


def _module_ns():
    """Exec the module's constants and defs without importing it (it is Qt-heavy).
    `def` does not run a body, so this is safe for the whole module."""
    with open(_REP, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.split("\n")
    ns = {"_json": json, "json": json, "re": re, "os": os,
          "Optional": typing.Optional, "Dict": dict, "Any": object,
          "List": list, "Tuple": tuple}
    for n in ast.parse(src).body:
        if isinstance(n, (ast.Assign, ast.AnnAssign, ast.FunctionDef)):
            try:
                exec(compile("\n".join(lines[n.lineno - 1:n.end_lineno]), _REP, "exec"), ns)
            except Exception:
                pass
    return ns


@pytest.fixture(scope="module")
def validate():
    ns = _module_ns()
    assert "_validate_report_json" in ns, "the validator moved — re-anchor this guard"
    return ns["_validate_report_json"]


@pytest.fixture(scope="module")
def prompt():
    return _module_ns()["build_report_system_prompt"]


def _ct(**over):
    base = {"Report Title": "CT of the Brain Without Contrast",
            "Pathological Findings": "Acute infarct.",
            "Normal Findings": "Cerebral parenchyma: normal."}
    base.update(over)
    return json.dumps(base)


# ── a normal study survives ──────────────────────────────────────────────────

@pytest.mark.parametrize("empty", ["", "   ", "N/A", "none", "-", "null", "nil"])
def test_an_empty_pathological_findings_is_a_normal_study(validate, empty):
    out = json.loads(validate(_ct(**{"Pathological Findings": empty}), "CT"))
    assert out["Pathological Findings"] == "No pathological findings are identified."


def test_a_null_pathological_findings_is_a_normal_study(validate):
    out = json.loads(validate(_ct(**{"Pathological Findings": None}), "CT"))
    assert out["Pathological Findings"] == "No pathological findings are identified."


def test_a_real_finding_is_never_overwritten(validate):
    """The coercion must only ever fire on an empty field."""
    out = json.loads(validate(_ct(**{"Pathological Findings": "Acute infarct."}), "CT"))
    assert out["Pathological Findings"] == "Acute infarct."


def test_mammography_normal_study_survives_too(validate):
    """Mammography has its own required-key list and the same bug."""
    payload = json.dumps({"Report Title": "Bilateral Mammography",
                          "Breast Composition": "ACR B",
                          "Pathological Findings": "",
                          "Normal Findings": "No suspicious findings.",
                          "Axillary Evaluation": "No lymphadenopathy.",
                          "BI-RADS Category": "1"})
    out = json.loads(validate(payload, "MAMOGRAPHY"))
    assert out["Pathological Findings"] == "No pathological findings are identified."


# ── but a broken response still fails loudly ─────────────────────────────────

def test_an_absent_key_still_raises(validate):
    """THE other edge. An absent key is truncated or garbled JSON, not a normal study.
    Coercing that too would turn a visible failure into a silently incomplete report."""
    payload = json.dumps({"Report Title": "CT Brain", "Normal Findings": "x"})
    with pytest.raises(Exception, match="Pathological Findings"):
        validate(payload, "CT")


@pytest.mark.parametrize("key", ["Report Title"])
def test_the_other_required_keys_are_still_strict(validate, key):
    """Narrowed 2026-08-09: 'Normal Findings' moved out of this list, see below.

    A report with no title is still a broken response, and nothing observed since
    suggests otherwise. Kept parametrised so the next key to earn an empty state is a
    one-line change with a reason attached, rather than a rewrite.
    """
    with pytest.raises(Exception, match=key):
        validate(_ct(**{key: ""}), "CT")


# ── the mirror: normals may be empty, because he may decline to dictate them ─

@pytest.mark.parametrize("empty", ["", "   ", "N/A", "none", "-", "null", "nil"])
def test_an_empty_normal_findings_no_longer_discards_the_report(validate, empty):
    """Patient 53673: "write only the ones I said". That is a legitimate request and
    the report must survive it."""
    out = json.loads(validate(_ct(**{"Normal Findings": empty}), "CT"))
    assert out["Normal Findings"] is None
    assert out["Pathological Findings"] == "Acute infarct.", "the pathology was lost"


def test_a_null_normal_findings_survives_too(validate):
    out = json.loads(validate(_ct(**{"Normal Findings": None}), "CT"))
    assert out["Normal Findings"] is None


def test_real_normal_findings_are_never_blanked(validate):
    out = json.loads(validate(_ct(**{"Normal Findings": "Cerebral parenchyma: normal."}),
                              "CT"))
    assert out["Normal Findings"] == "Cerebral parenchyma: normal."


def test_an_absent_normal_findings_still_raises(validate):
    """The truncated-JSON signal has to survive the relaxation. Empty is a choice;
    absent is a broken response."""
    payload = json.dumps({"Report Title": "CT Brain",
                          "Pathological Findings": "Acute infarct."})
    with pytest.raises(Exception, match="Normal Findings"):
        validate(payload, "CT")


def test_normals_are_nulled_and_never_given_an_invented_sentence(validate):
    """The asymmetry with pathology, asserted directly. A substituted sentence here
    would claim structures were examined and normal when nobody said so."""
    out = json.loads(validate(_ct(**{"Normal Findings": ""}), "CT"))
    assert out["Normal Findings"] is None
    assert not isinstance(out["Normal Findings"], str)


@pytest.mark.parametrize("modality", ["CT", "MRI", "SONOGRAPHY"])
def test_the_relaxation_covers_the_plain_string_modalities(validate, modality):
    out = json.loads(validate(_ct(**{"Normal Findings": ""}), modality))
    assert out["Normal Findings"] is None


def test_mammography_normal_findings_stays_strict(validate):
    """Deliberately NOT relaxed. Mammography's required keys are the ones the referring
    clinician acts on, its 'Normal Findings' is a per-breast dict rather than a string,
    and no failure has been observed there. Relaxing it would be a guess."""
    payload = json.dumps({"Report Title": "Bilateral Mammography",
                          "Breast Composition": "ACR B",
                          "Pathological Findings": "Mass upper outer quadrant.",
                          "Normal Findings": "",
                          "Axillary Evaluation": "No lymphadenopathy.",
                          "BI-RADS Category": "4"})
    with pytest.raises(Exception, match="Normal Findings"):
        validate(payload, "MAMOGRAPHY")


def test_obstetric_ultrasound_stays_strict_as_well(validate):
    payload = json.dumps({"Report Title": "Obstetric Ultrasound",
                          "Gestational Age & Dating": "22w0d",
                          "Fetal Presentation": "Cephalic",
                          "Biometry": "AC 180mm",
                          "Placenta & Umbilical Cord": "Anterior",
                          "Amniotic Fluid": "Normal",
                          "Normal Findings": ""})
    with pytest.raises(Exception, match="Normal Findings"):
        validate(payload, "OBSTETRIC ULTRASOUND")


# ── and the prompt asks for it explicitly ────────────────────────────────────

@pytest.mark.parametrize("modality", ["CT", "MRI", "SONOGRAPHY", "OBSTETRIC ULTRASOUND",
                                      "RADIOLOGY", "MAMOGRAPHY", ""])
def test_the_prompt_requires_an_explicit_normal_statement(prompt, modality):
    """Belt and braces: the validator will repair an empty field, but the model should
    not be producing one in the first place."""
    p = prompt(modality, "")
    assert "A COMPLETELY NORMAL STUDY IS A VALID REPORT" in p
    seg = " ".join(p[p.index("A COMPLETELY NORMAL STUDY IS A VALID REPORT"):][:700].split())
    assert "'No pathological findings are identified.'" in seg
    assert "Do NOT invent a finding to fill it" in seg


# ── paranasal sinus CT gets its own structures ───────────────────────────────

def test_ct_has_a_paranasal_sinus_grouping(prompt):
    """A CT of the paranasal sinuses reported orbits and dentition as normal but not
    the sinuses themselves — they existed only as one bullet inside 'Brain'."""
    p = prompt("CT", "")
    assert "Paranasal sinuses: Maxillary sinuses" in p
    i = p.index("Paranasal sinuses: Maxillary sinuses")
    seg = " ".join(p[i:i + 400].split())
    for structure in ("Ethmoid air cells", "Frontal sinuses", "Sphenoid sinus",
                      "Ostiomeatal complexes", "Nasal septum"):
        assert structure in seg, f"the sinus set is missing {structure}"


@pytest.mark.parametrize("tag", ["SINUS", "SINUSES", "PNS", "PARANASALSINUS"])
def test_sinus_dicom_tags_map_to_a_region(tag):
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from modules.EchoMind import session_metadata as sm
    assert sm.normalize_region(tag) == ("paranasal_sinuses",)


def test_the_new_region_is_canonical():
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from modules.EchoMind import session_metadata as sm
    assert "paranasal_sinuses" in sm.REGION_KEYS
    for regions in sm._DICOM_REGION_MAP.values():
        for r in regions:
            assert r in sm.REGION_KEYS, f"{r} is not a canonical region key"


# ── the message the physician reads says it once ─────────────────────────────

def test_the_failure_text_is_not_double_wrapped():
    """Production showed: "The AI request failed. Detail: The AI request failed.
    Detail: ..." — the classifier's own output fed back in as its input."""
    path = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_helpers.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    assert "_unwrap_own_wrapper" in src
    assert "_unwrap_own_wrapper(_redact_endpoint_details(s))" in src, (
        "the unwrapper is defined but not applied to the incoming detail"
    )
    i = src.index("def _unwrap_own_wrapper")
    body = src[i:src.index("\ndef ", i + 10)]
    assert "for _ in range(" in body, "the unwrap loop is unbounded"
