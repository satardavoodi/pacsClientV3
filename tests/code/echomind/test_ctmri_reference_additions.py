"""Guard: the CT/MRI additions distilled from the physician's proven 6-month
reference prompt, and the safe example dedup (2026-08-02).

Added (once, in the shared assembly, so CT and MRI both carry them):
  * certainty-preservation ladder — a hedge is a clinical claim; "may represent"
    must not become "represents". This is the single strongest thing the
    reference prompt had that EchoMind lacked.
  * standardized-systems list + classification guardrails — the -RADS systems
    standardise wording, never manufacture a category the criteria don't support.
  * qualified-normal register — for auto-generated normals the model states
    "No gross abnormality is identified" by default, switching to definitive
    normals only when the physician signals the rest is normal.

Removed:
  * the DUPLICATE MRI examples (Brain and Knee appeared twice; the second pair
    was the redundant/contradictory copy). The four distinct examples stay.

Same extraction harness as the other prompt tests (the module is Qt-heavy).
"""

import os
import typing

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_REPORTER_PY = os.path.normpath(
    os.path.join(_THIS, "..", "..", "..", "modules", "EchoMind", "viewer_chat", "openai_reporter.py")
)
_UI = ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY"]


def _prompt_fn():
    import ast

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


# ── certainty ladder ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("modality", _UI)
def test_certainty_ladder_present(modality, prompt):
    sp = prompt(modality, "")
    assert "Preserve the physician's degree of certainty exactly" in sp
    for pair in [
        "'may represent' must not become 'represents'",
        "'suspicious for' must not become 'consistent with'",
        "'cannot be excluded' must stay uncertain",
        "'favored to represent' must not become a definitive diagnosis",
        "'less likely' must remain a secondary possibility",
    ]:
        assert pair in sp, f"{modality}: certainty ladder missing pair: {pair}"


def test_certainty_ladder_lives_inside_source_fidelity(prompt):
    """It's a fidelity rule — it should sit in the one contract, not float free."""
    sp = prompt("CT", "")
    i = sp.index("SOURCE FIDELITY")
    j = sp.index("STANDARDIZED SYSTEMS")
    assert i < sp.index("degree of certainty") < j


# ── standardized systems + guardrails ────────────────────────────────────────

@pytest.mark.parametrize("modality", _UI)
def test_standardized_systems_block_present(modality, prompt):
    sp = prompt(modality, "")
    assert "STANDARDIZED SYSTEMS — use them to standardise wording, never to manufacture a category." in sp
    for system in ["BI-RADS", "TI-RADS", "PI-RADS", "LI-RADS", "O-RADS", "Bosniak", "CAD-RADS"]:
        assert system in sp, f"{modality}: standardized system {system} missing"


@pytest.mark.parametrize("modality", _UI)
def test_classification_guardrails_present(modality, prompt):
    sp = prompt(modality, "")
    assert "Apply a category ONLY when the dictated information meets" in sp
    assert "do not invent a measurement, descriptor, or risk factor" in sp
    assert "When the physician dictates a category, preserve it" in sp


def test_standardized_block_is_stated_once(prompt):
    assert prompt("MRI", "").count("STANDARDIZED SYSTEMS — use them") == 1


# ── qualified-normal register ────────────────────────────────────────────────

@pytest.mark.parametrize("modality", _UI)
def test_qualified_normal_register_present(modality, prompt):
    sp = prompt(modality, "")  # no-template path — where normals are auto-generated
    assert "QUALIFIED register" in sp
    assert "No gross abnormality is identified" in sp
    assert "Within the limits of the" in sp


def test_rest_is_normal_switches_to_definitive(prompt):
    """2026-08-07 — REWRITTEN, same intent, stronger rule.

    This used to read: "If the physician DID indicate the remainder is normal ...
    you MAY state definitive normal findings". Patient 53516 showed why that failed —
    a PERMISSIVE clause competing with a DIRECTIVE qualified-register default loses.
    The physician asked for the normal report («کد طبیعی») and received hedged
    "no gross abnormality" text that he then had to rewrite by hand.

    The switch is now mandatory, and the Persian triggers are named so the request is
    recognisable in the language it is actually dictated in. The full guard — trigger
    list, granularity rule, RSNA worked example — is in
    test_normal_findings_register.py.
    """
    sp = prompt("CT", "")
    assert "THE NORMAL-REPORT REQUEST" in sp
    assert "MUST switch to DEFINITIVE normal findings" in sp
    assert "you MAY state definitive" not in sp, "the permissive wording is back"


def test_qualified_register_only_on_the_auto_normals_path(prompt):
    """When the physician supplies their own template, the template drives the
    normals — the qualified auto-normal register does not apply."""
    with_tpl = prompt("MRI", "Both menisci demonstrate normal morphology and signal intensity.")
    # the template fence + rules are what govern here
    assert "===== NORMAL_TEMPLATE" in with_tpl


# ── the dedup: duplicate examples gone, distinct set intact ──────────────────

def test_duplicate_mri_examples_removed(prompt):
    mri = prompt("MRI", "")
    assert mri.count("MRI of the Brain With and Without Contrast, Including DWI and MR Spectroscopy") == 1, (
        "the Brain example is duplicated again"
    )
    assert mri.count("MRI of the Right Knee Joint Without Contrast") == 1, "the Knee example is duplicated again"


def test_the_four_distinct_examples_are_kept(prompt):
    mri = prompt("MRI", "")
    for case in [
        "MRI of the Brain With and Without Contrast",
        "MRI of the Right Knee Joint Without Contrast",
        "MRI of the Lumbar Spine Without Contrast",
        "MRI of Both Breasts With Contrast",
    ]:
        assert case in mri, f"a distinct example was lost: {case}"


# ── nothing essential was collateral damage ──────────────────────────────────

def test_json_output_rules_preserved(prompt):
    # Every modality carries its JSON output contract via the "Report Title" key.
    for m in _UI:
        assert '"Report Title"' in prompt(m, ""), f"{m}: JSON schema (Report Title) lost"
    # The four general modalities use the shared OUTPUT FORMAT (STRICT) block…
    for m in ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY"]:
        assert "OUTPUT FORMAT (STRICT)" in prompt(m, ""), f"{m}: OUTPUT FORMAT rules lost"
    # …while MAMOGRAPHY has always used its own, even stricter, regex-locked schema.
    mamo = prompt("MAMOGRAPHY", "")
    assert "REGEX-LOCKED JSON SCHEMA" in mamo, "MAMOGRAPHY regex-locked schema lost"


def test_modality_content_preserved(prompt):
    assert "BI-RADS" in prompt("MAMOGRAPHY", "")
    assert "ISUOG" in prompt("SONOGRAPHY", "")
    assert "SOURCE FIDELITY" in prompt("CT", "")
    # the MRI normal-template library survived the example dedup
    mri = prompt("MRI", "")
    assert "Menisci" in mri or "Ventricular System" in mri


def test_both_backends_still_identical(monkeypatch):
    import importlib

    rep = importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")
    twin = importlib.import_module("modules.EchoMind.viewer_chat.openai_parallel_backend")
    cap = {}
    monkeypatch.setattr(twin, "_call", lambda **k: (cap.update(k), {"content": "{}", "usage": {}})[1])
    monkeypatch.setattr(twin, "_feature_prompt", lambda n: "")
    monkeypatch.setattr(twin, "_validate_report_json", lambda raw, m: raw)
    twin.reporter(user_msg="x", modality="MRI")
    assert cap["system_prompt"] == rep.build_report_system_prompt("MRI", "")
    assert "degree of certainty" in cap["system_prompt"]
    assert "STANDARDIZED SYSTEMS" in cap["system_prompt"]
