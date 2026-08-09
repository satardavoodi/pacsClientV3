"""Guard: every modality reaches a real branch, and nothing can produce a prompt
without a JSON output contract (2026-08-08).

FOUND BY AUDIT, not by a failure. Two holes that compounded:

  1. `build_report_system_prompt` did `modality.lower()` with no `.strip()`, while the
     four UI entry points guard only on emptiness. `' CT '` is truthy, matched no
     branch, and landed in the generic fallback. The sampling-params helper one
     function above ALREADY did `.strip().lower()`, so the two disagreed about the
     same input: `' CT '` got the validated temperature/max_tokens while its prompt
     fell through.
  2. Neither generic fallback stated an OUTPUT FORMAT contract — no JSON schema at
     all — so anything reaching them returned prose the parser cannot read. A failure
     with no diagnosable cause.

Neither was reachable from the UI when found. That is precisely why they were worth
closing: nothing would have raised, and `_current_modality` is persisted state, so
"the combo only emits clean values" is a fact about today, not a guarantee.
"""

import ast
import importlib.util
import os
import sys
import typing

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
_REPORTER = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "openai_reporter.py")


def _build():
    with open(_REPORTER, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.split("\n")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "build_report_system_prompt")
    ns = {"_to_str": lambda x: "" if x is None else str(x),
          "Optional": typing.Optional, "Dict": dict, "Any": object}
    exec(compile("\n".join(lines[node.lineno - 1:node.end_lineno]), _REPORTER, "exec"), ns)
    return ns["build_report_system_prompt"]


@pytest.fixture(scope="module")
def prompt():
    return _build()


def _ui_modalities():
    """Read the real UI list, so adding a modality to the combo fails these tests
    until its branch exists — that is the point."""
    p = os.path.join(_ROOT, "modules", "EchoMind", "ai_chat_config.py")
    spec = importlib.util.spec_from_file_location("_em_cfg", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.REPORT_MODALITIES)


UI = _ui_modalities()


def _contract(p):
    if "REGEX-LOCKED JSON SCHEMA" in p:
        return "MAMMO"
    if "ISUOG Structured Report" in p:
        return "ISUOG"
    if "OUTPUT FORMAT (STRICT)" in p:
        return "STRICT-5"
    return None


# ── 1. every UI option reaches a real branch ─────────────────────────────────

def test_the_ui_list_is_what_we_think_it_is():
    assert UI, "REPORT_MODALITIES is empty — the UI offers nothing"
    assert "OBSTETRIC ULTRASOUND" in UI, "OB was activated on 2026-08-06; it is gone"


@pytest.mark.parametrize("modality", UI)
def test_every_ui_modality_reaches_a_real_branch(modality, prompt):
    """A modality in the combo with no branch behind it silently produces the thin
    generic prompt. Reading the list from config means a new combo entry fails here."""
    p = prompt(modality, "")
    assert _contract(p) is not None, f"{modality!r} has no output contract"
    assert len(p) > 25_000, (
        f"{modality!r} produced only {len(p)} chars — that is the generic fallback, "
        "not a real modality branch"
    )


@pytest.mark.parametrize("modality", UI)
@pytest.mark.parametrize("pad", ["{} ", " {}", " {} ", "\t{}\t", "  {}  "])
def test_whitespace_cannot_derail_the_dispatch(modality, pad, prompt):
    """The bug: guards test emptiness, dispatch tests exact keys, and ' CT ' passes the
    first and fails the second."""
    padded = pad.format(modality)
    assert _contract(prompt(padded, "")) == _contract(prompt(modality, "")), (
        f"{padded!r} routes differently from {modality!r}"
    )


@pytest.mark.parametrize("modality", UI)
def test_case_cannot_derail_the_dispatch(modality, prompt):
    for variant in (modality.lower(), modality.upper(), modality.title()):
        assert _contract(prompt(variant, "")) == _contract(prompt(modality, "")), (
            f"{variant!r} routes differently from {modality!r}"
        )


# ── 2. nothing can produce a prompt with no contract ─────────────────────────

@pytest.mark.parametrize("value", ["", None, "   ", "x-ray", "PET-CT",
                                   "nuclear medicine", "whatever"])
def test_no_input_can_produce_a_prompt_without_a_contract(value, prompt):
    """The fallbacks are unreachable today. If that ever changes, the report must still
    be PARSEABLE — a prompt with no schema yields prose, and the physician sees a
    failure with no cause."""
    assert _contract(prompt(value, "")) is not None, (
        f"modality={value!r} produced a prompt with no JSON output contract"
    )


@pytest.mark.parametrize("value", ["", "x-ray"])
def test_the_fallback_contract_is_the_standard_five_keys(value, prompt):
    """So a fallback report parses through exactly the same path as a real one."""
    p = prompt(value, "")
    seg = " ".join(p[p.index("OUTPUT FORMAT (STRICT)"):][:1200].split())
    for key in ("Report Title", "Pathological Findings", "Normal Findings",
                "Impression", "Recommendations"):
        assert f'"{key}"' in seg, f"the fallback contract is missing {key!r}"


# ── 3. the two normalisers must not disagree again ───────────────────────────

def test_the_builder_strips_like_the_sampling_helper_does():
    """These two read the same argument. When only one stripped, ' CT ' got validated
    sampling params and an unvalidated prompt."""
    with open(_REPORTER, encoding="utf-8") as fh:
        src = fh.read()
    assert "_to_str(modality).strip().lower()" in src, "the sampling helper stopped stripping"
    i = src.index("def build_report_system_prompt")
    head = src[i:i + 2500]
    assert "modality = _to_str(modality).strip()" in head, (
        "the prompt builder no longer strips the modality"
    )
