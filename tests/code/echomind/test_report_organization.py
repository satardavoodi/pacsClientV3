"""Guard: REPORT ORGANIZATION — anatomical sub-structure inside every section
(2026-08-06, owner-requested after a real chest+abdomen+pelvis CT).

The defect: the report separated Pathological / Normal / Impression /
Recommendations, but the content INSIDE each section was one flat paragraph. On a
multi-region study the reader could not scan for an organ.

The root cause: the ONLY grouping instruction — "Use structured, grouped,
RSNA-style anatomical organisation" — sits inside MODALITY LOGIC between two
Normal-Findings lines, so the model applied it to the normals only. That is
exactly what the live output showed: grouped normals, flat pathology.

The fix pinned here: ONE shared REPORT ORGANIZATION block in the shared assembly
(every modality inherits it) covering BOTH findings sections, with the
region-first / organ-first choice, a worked example, and two deferrals.

CRITICAL INVARIANT: the rule arranges text INSIDE the existing JSON string
values. It must never be readable as licence to add keys or nest objects — the
renderer, `_validate_report_json`, Reception and the correction KEY-SET MIRROR
all depend on the flat key set.
"""

import ast
import os
import typing

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_REPORTER_PY = os.path.normpath(
    os.path.join(_THIS, "..", "..", "..", "modules", "EchoMind", "viewer_chat", "openai_reporter.py")
)
_UI = ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY"]
_KNEE_TEMPLATE = "Both menisci demonstrate normal morphology and signal intensity."


def _prompt_fn():
    with open(_REPORTER_PY, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.split("\n")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "build_report_system_prompt")
    body = "\n".join(lines[node.lineno - 1:node.end_lineno])
    ns = {"_to_str": lambda x: "" if x is None else str(x),
          "Optional": typing.Optional, "Dict": dict, "Any": object}
    exec(compile(body, _REPORTER_PY, "exec"), ns)
    return ns["build_report_system_prompt"]


@pytest.fixture(scope="module")
def prompt():
    return _prompt_fn()


# ── present once, in every modality ──────────────────────────────────────────

@pytest.mark.parametrize("modality", _UI)
def test_rule_present_once(modality, prompt):
    sp = prompt(modality, "")
    assert "REPORT ORGANIZATION — group the content INSIDE every findings section." in sp
    assert sp.count("REPORT ORGANIZATION — group") == 1, "shared block must be stated once"


def test_rule_sits_in_the_shared_assembly(prompt):
    """Between the other shared contracts and the modality block, so it governs
    the modality rules rather than being scoped by one of them."""
    sp = prompt("CT", "")
    assert sp.index("SOURCE FIDELITY") < sp.index("REPORT ORGANIZATION") < sp.index("MODALITY LOGIC")


# ── it covers BOTH sections (the actual defect) ──────────────────────────────

@pytest.mark.parametrize("modality", _UI)
def test_covers_pathological_and_normal(modality, prompt):
    sp = prompt(modality, "")
    assert "applies to BOTH 'Pathological Findings' and" in sp, (
        f"{modality}: the rule must not be readable as Normal-Findings-only — that was the bug"
    )


# ── the grouping choice: region-first vs organ-first ─────────────────────────

def test_multi_region_groups_by_region(prompt):
    sp = prompt("CT", "")
    assert "MULTI-REGION study" in sp
    assert "'Chest:', 'Abdomen:', 'Pelvis:'" in sp


def test_single_region_groups_by_structure(prompt):
    sp = prompt("MRI", "")
    assert "SINGLE-REGION study is grouped by ORGAN, STRUCTURE or SYSTEM" in sp
    for structure in ["'Menisci:'", "'Cruciate ligaments:'", "'Cartilage:'", "'Bone marrow:'"]:
        assert structure in sp, f"knee-MRI worked structure missing: {structure}"


def test_reuses_the_modality_vocabulary(prompt):
    """The per-region organ names already live in the modality rules — the model
    must reuse them, not invent a parallel vocabulary."""
    assert "do not invent a different vocabulary" in prompt("CT", "")


def test_has_a_worked_example(prompt):
    sp = prompt("CT", "")
    assert "Worked example" in sp
    assert "Chest:" in sp and "Abdomen:" in sp


# ── the guards that keep it from becoming a new defect ───────────────────────

def test_no_empty_or_uncovered_headings(prompt):
    """A heading asserts the region was examined — that is a SOURCE FIDELITY claim."""
    sp = prompt("CT", "")
    assert "Emit a heading ONLY when it has content" in sp
    assert "is a claim that the region was examined" in sp


def test_proportion_guard(prompt):
    """A two-finding single-region study must not be fragmented into headings."""
    assert "never fragment a two-line report" in prompt("CT", "")


def test_grouping_never_moves_content_between_sections(prompt):
    assert "Grouping NEVER moves content between sections" in prompt("CT", "")


def test_impression_is_ordered_not_regionally_grouped(prompt):
    sp = prompt("CT", "")
    assert "list its items in order of clinical importance" in sp
    assert "Do not add regional headings to the Impression." in sp


# ── THE critical invariant: no JSON schema drift ─────────────────────────────

@pytest.mark.parametrize("modality", _UI)
def test_json_key_set_is_explicitly_protected(modality, prompt):
    sp = prompt(modality, "")
    assert "ARRANGES TEXT INSIDE THE EXISTING JSON STRING VALUES" in sp
    assert "do not add keys, do not rename keys" in sp
    assert "nested object" in sp, "must forbid turning a string value into an object"


@pytest.mark.parametrize("modality", _UI)
def test_modality_defined_structure_wins(modality, prompt):
    """Mammography's per-breast schema must not get a second grouping on top."""
    assert "THAT structure wins" in prompt(modality, "")


def test_supplied_template_structure_governs_the_normals(prompt):
    """When the physician supplies a Normal Template, THEIR structure wins — the
    organization rule must not re-group the physician's own template."""
    with_tpl = prompt("MRI", _KNEE_TEMPLATE)
    assert "the template's OWN section structure governs 'Normal Findings'" in with_tpl
    assert "Do NOT re-group the physician's" in with_tpl
    # …and that deferral only exists on the template path
    assert "the template's OWN section structure governs" not in prompt("MRI", "")


# ── nothing else regressed ───────────────────────────────────────────────────

def test_existing_contracts_intact(prompt):
    for m in _UI:
        sp = prompt(m, "")
        assert "SOURCE FIDELITY — the medical content comes only from the physician." in sp
        assert "Preserve the physician's degree of certainty exactly" in sp
        assert "STANDARDIZED SYSTEMS — use them" in sp
    for m in ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY"]:
        assert "OUTPUT FORMAT (STRICT)" in prompt(m, "")
    assert "REGEX-LOCKED JSON SCHEMA" in prompt("MAMOGRAPHY", "")
    assert "ISUOG" in prompt("SONOGRAPHY", "")
    assert prompt("MRI", "").count("## ✅ MRI Example") == 4
    assert "PLACEHOLDER VALUES" in prompt("SONOGRAPHY", "The uterus measures ___.")


def test_both_backends_carry_it(monkeypatch):
    import importlib

    rep = importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")
    twin = importlib.import_module("modules.EchoMind.viewer_chat.openai_parallel_backend")
    cap = {}
    monkeypatch.setattr(twin, "_call", lambda **k: (cap.update(k), {"content": "{}", "usage": {}})[1])
    monkeypatch.setattr(twin, "_feature_prompt", lambda n: "")
    monkeypatch.setattr(twin, "_validate_report_json", lambda raw, m: raw)
    twin.reporter(user_msg="x", modality="CT")
    assert "REPORT ORGANIZATION" in cap["system_prompt"]
    assert cap["system_prompt"] == rep.build_report_system_prompt("CT", "")


# ═════════════════════════════════════════════════════════════════════════════
# ALL MODALITIES — not just CT (owner directive 2026-08-06)
#
# `build_report_system_prompt` has SIX modality branches plus a generic
# fallback. The obstetric branch is separate from the sonography branch and was
# not covered by the first pass:
#   ct | mri | obstetric-ultrasound | sonography/ultrasound | mammography |
#   radiology | (generic fallback)
# Every one of them must carry the shared rule, and each must have a grouping
# vocabulary appropriate to it — either its own list, or its own structured
# schema (mammography's per-breast, obstetric's ISUOG) which governs instead.
# ═════════════════════════════════════════════════════════════════════════════

_ALL_BRANCH_VALUES = [
    "CT", "MRI", "SONOGRAPHY", "ULTRASOUND", "RADIOLOGY",
    "MAMOGRAPHY", "MAMOGRAM", "mammography",
    "Obstetric Ultrasound", "OB Ultrasound", "pregnancy ultrasound", "fetal ultrasound",
    "", "SomeUnknownModality",
]


@pytest.mark.parametrize("modality", _ALL_BRANCH_VALUES)
def test_shared_rule_reaches_every_branch(modality, prompt):
    """Including the obstetric branch and the generic fallback."""
    sp = prompt(modality, "")
    assert "REPORT ORGANIZATION — group the content INSIDE every findings section." in sp, (
        f"{modality!r}: shared organization rule missing"
    )


@pytest.mark.parametrize("modality,needles", [
    ("CT", ["GROUPING VOCABULARY (CT)", "Gallbladder and biliary tree",
            "Ventricular system and midline", "Facet joints"]),
    ("MRI", ["GROUPING VOCABULARY (MRI)", "Menisci · Cruciate ligaments",
             "Rotator cuff", "Conus and cauda equina"]),
    ("SONOGRAPHY", ["GROUPING VOCABULARY (ULTRASOUND)", "Right testis",
                    "Endometrium", "Aorta and IVC"]),
    ("RADIOLOGY", ["GROUPING VOCABULARY (RADIOGRAPHY)", "Bowel gas pattern",
                   "Lines and tubes", "Disc spaces"]),
])
def test_each_modality_has_its_own_vocabulary(modality, needles, prompt):
    sp = prompt(modality, "")
    for n in needles:
        assert n in sp, f"{modality}: grouping vocabulary missing {n!r}"


def test_mammography_schema_is_the_organization(prompt):
    sp = prompt("MAMOGRAPHY", "")
    assert "REPORT ORGANIZATION (MAMMOGRAPHY)" in sp
    assert "per-breast schema IS this report's organization" in sp
    assert "Do NOT impose additional regional headings" in sp
    assert "rename or nest any JSON key" in sp


def test_obstetric_isuog_structure_is_the_organization(prompt):
    sp = prompt("Obstetric Ultrasound", "")
    assert "REPORT ORGANIZATION (OBSTETRIC)" in sp
    assert "ISUOG section structure above" in sp
    assert "keep fetal anatomy findings together by system" in sp
    assert "rename or nest any JSON key" in sp
    # the OB branch keeps its own schema
    assert "JSON OUTPUT SCHEMA (ISUOG — STRICT)" in sp


@pytest.mark.parametrize("ob_value", ["Obstetric Ultrasound", "OB Ultrasound",
                                      "pregnancy ultrasound", "fetal ultrasound"])
def test_every_obstetric_alias_gets_it(ob_value, prompt):
    sp = prompt(ob_value, "")
    assert "REPORT ORGANIZATION" in sp
    assert "REPORT ORGANIZATION (OBSTETRIC)" in sp


def test_no_cross_modality_vocabulary_leak(prompt):
    """Each prompt carries ONLY its own vocabulary — no bulk from other modalities."""
    assert "GROUPING VOCABULARY (MRI)" not in prompt("CT", "")
    assert "GROUPING VOCABULARY (CT)" not in prompt("MRI", "")
    assert "GROUPING VOCABULARY (ULTRASOUND)" not in prompt("RADIOLOGY", "")
    assert "GROUPING VOCABULARY (RADIOGRAPHY)" not in prompt("SONOGRAPHY", "")
    # the two schema-owning branches take a deferral line, not a vocabulary list
    assert "GROUPING VOCABULARY" not in prompt("Obstetric Ultrasound", "")


def test_modality_content_survived_the_vocabulary_insert(prompt):
    assert "REGEX-LOCKED JSON SCHEMA" in prompt("MAMOGRAPHY", "")
    assert "BI-RADS" in prompt("MAMOGRAPHY", "")
    assert "ISUOG" in prompt("SONOGRAPHY", "")
    assert "NON-OBSTETRIC ULTRASOUND — EXAM-SPECIFIC NORMAL TEMPLATES" in prompt("SONOGRAPHY", "")
    assert "RSNA NORMAL FINDINGS — GENERAL X-RAY" in prompt("RADIOLOGY", "")
    assert "MODALITY LOGIC (CT)" in prompt("CT", "")
    assert prompt("MRI", "").count("## ✅ MRI Example") == 4
