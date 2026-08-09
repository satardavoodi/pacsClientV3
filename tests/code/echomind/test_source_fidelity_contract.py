"""Guard: the SOURCE FIDELITY contract — no invented findings, no changed anatomy,
frozen negatives, no normal/pathological contradiction (2026-08-02).

Driven by a real customer failure on the Turbo path. The physician dictated a
right occipito-parietal hypodensity with **no hemorrhage**; the model reported it
in the **frontal** lobe, added **hyperdense areas** (an invented hemorrhage the
physician had ruled out), dropped the sulcal effacement and the MRI
recommendation, and then wrote "gray-white differentiation preserved throughout"
over the infarcted territory.

Root cause: every modality prompt forbade inventing a new IMPRESSION but none
forbade inventing a FINDING, changing the stated ANATOMY, or reversing a stated
NEGATIVE — and only CT (region-level) excluded an abnormal structure from Normal
Findings. This test pins the unified contract that closes all of it, stated once
and applied to every modality, plus the removal of the live contradiction that
told the model to "Construct Normal Findings automatically" while other rules
said "don't invent".

Extraction harness matches the other prompt tests: the module is heavy to import
(Qt/app deps), so we exec just ``build_report_system_prompt`` with light stubs.
The contract is an INLINE local in that function, so the extracted source carries
the real text — no stub, no vacuous assertion.
"""

import os
import typing

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_REPORTER_PY = os.path.normpath(
    os.path.join(_THIS, "..", "..", "..", "modules", "EchoMind", "viewer_chat", "openai_reporter.py")
)

_UI_MODALITIES = ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY"]
_KNEE_TEMPLATE = "Both menisci demonstrate normal morphology and signal intensity."


def _build_prompt_fn():
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
    return _build_prompt_fn()


# ─────────────────────────────────────────────────────────────────────────────
# 1. The contract is present in every modality, stated once
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("modality", _UI_MODALITIES)
def test_contract_present(modality, prompt):
    sp = prompt(modality, "")
    assert "SOURCE FIDELITY — the medical content comes only from the physician." in sp, (
        f"{modality}: the source-fidelity contract is missing"
    )


@pytest.mark.parametrize("modality", _UI_MODALITIES)
def test_contract_stated_once(modality, prompt):
    """The full contract block appears exactly once — not duplicated per section.
    (A short back-reference 'bound by SOURCE FIDELITY above' is allowed and is
    NOT the block.)"""
    sp = prompt(modality, "")
    assert sp.count("SOURCE FIDELITY — the medical content comes only from the physician.") == 1


@pytest.mark.parametrize("modality", _UI_MODALITIES)
def test_contract_precedes_the_modality_block(modality, prompt):
    """Fidelity is stated before the modality rules, so it governs them."""
    sp = prompt(modality, "")
    assert sp.index("SOURCE FIDELITY") < sp.index("MODALITY LOGIC")


# ─────────────────────────────────────────────────────────────────────────────
# 2. The five rules the customer failure needed
# ─────────────────────────────────────────────────────────────────────────────

_RULES = {
    "no invented finding": "Do not add a finding, a diagnosis, or an",
    "no changed anatomy/location": "Keep the anatomy and laterality exactly as dictated",
    "frozen negative": "A stated negative stays negative",
    "no dropped content": "Do not drop what the physician stated",
    "no normal/pathological contradiction": "Normal findings must not contradict the pathology",
    "uncertain → omit": "If you are unsure whether the physician stated something, leave it out",
}


@pytest.mark.parametrize("rule,needle", sorted(_RULES.items()))
def test_each_rule_is_stated(rule, needle, prompt):
    sp = prompt("CT", "")
    assert needle in sp, f"fidelity contract is missing the rule: {rule}"


def test_worked_examples_are_from_real_failures(prompt):
    """Examples beat prose — and these are the exact failures we saw."""
    sp = prompt("CT", "")
    # the anatomy example (occipito-parietal, not frontal)
    assert "right occipital and parietal lobes" in sp
    # the frozen-negative example (no hemorrhage)
    assert "no hemorrhage" in sp
    # the contradiction example (gallbladder — the physician's own example)
    assert "the gallbladder is normal" in sp
    assert "gallbladder stones are present" in sp.lower()


def test_paired_structure_split_is_covered(prompt):
    sp = prompt("CT", "")
    assert "paired or grouped" in sp
    assert "keep the normal statement only for the members" in sp


# ─────────────────────────────────────────────────────────────────────────────
# 3. The auto-normals contradiction is resolved (not by removing auto-normals)
# ─────────────────────────────────────────────────────────────────────────────

def test_the_live_contradiction_is_gone(prompt):
    """GPT-5.6 treats contradictory rules as destabilising. The no-template branch
    used to say 'Construct Normal Findings automatically' with no fidelity binding,
    next to rules that said 'don't invent'."""
    sp = prompt("CT", "")
    assert "Construct 'Normal Findings' automatically" not in sp
    assert "Exclude any organ mentioned in Pathological Findings" not in sp


def test_auto_normals_are_kept_but_bound(prompt):
    """The physician's decision: auto-generated normals STAY (they dictate only
    pathology), but bound so they can never contradict the pathology."""
    sp = prompt("CT", "")
    assert "you generate the Normal Findings" in sp, "auto-normals were removed — they must stay"
    assert "RSNA-style normal structure" in sp, "the existing RSNA structure must be preserved"
    assert "bound by SOURCE FIDELITY above" in sp, "auto-normals must be bound to the fidelity contract"


def test_existing_modality_content_preserved(prompt):
    """The mature modality-specific content must not have been collateral damage."""
    assert "BI-RADS" in prompt("MAMOGRAPHY", "")
    assert "OUTPUT FORMAT (STRICT)" in prompt("CT", "")
    assert "ISUOG" in prompt("SONOGRAPHY", "")  # obstetric rules retained
    # with a template, yesterday's paired-structure + fence rules still coexist
    wt = prompt("MRI", _KNEE_TEMPLATE)
    assert "===== NORMAL_TEMPLATE" in wt and "PARTIAL INVOLVEMENT" in wt


# ─────────────────────────────────────────────────────────────────────────────
# 4. Both backends carry it (the twin calls the same builder)
# ─────────────────────────────────────────────────────────────────────────────

def test_the_openai_twin_sends_the_contract(monkeypatch):
    import importlib

    rep = importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")
    twin = importlib.import_module("modules.EchoMind.viewer_chat.openai_parallel_backend")
    cap = {}
    monkeypatch.setattr(twin, "_call", lambda **k: (cap.update(k), {"content": "{}", "usage": {}})[1])
    monkeypatch.setattr(twin, "_feature_prompt", lambda n: "")
    monkeypatch.setattr(twin, "_validate_report_json", lambda raw, m: raw)
    twin.reporter(user_msg="tear of the lateral meniscus", modality="CT")
    assert "SOURCE FIDELITY" in cap["system_prompt"]
    assert cap["system_prompt"] == rep.build_report_system_prompt("CT", "")
