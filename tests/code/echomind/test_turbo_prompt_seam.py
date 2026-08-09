"""Guard: Turbo has its own prompt builder, and today it changes nothing (2026-08-08).

OWNER DECISION: Turbo diverges from the Send path. The obstacle is that
`openai_reporter.reporter` serves BOTH — Turbo always, and Send whenever the Settings
backend is `company`, which is the default. So the split cannot live inside that
function; it is made at the Turbo CALL SITE, the only place that knows it is Turbo.

PHASE 1 IS DELIBERATELY A NO-OP ON THE PROMPT TEXT. Turbo's builder returns output
byte-identical to the shared builder. A refactor that also changes behaviour is two
changes wearing one diff, and when report quality moves you cannot tell which half did
it. These tests pin the identity so the gating change that follows is a single reviewable
diff against a known-good baseline.

The load-bearing properties:

  1. Byte-identical output, every modality, with and without a normal template.
  2. Send is untouched — its call site passes no override, and the parallel backend
     does not know the parameter exists.
  3. The override defaults to None, so every existing caller behaves exactly as before.
  4. A failure in Turbo's builder degrades to the shared prompt; it never breaks a report.
"""

import ast
import io
import os
import sys
import typing

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_REPORTER = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "openai_reporter.py")
_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")
_PARALLEL = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat",
                         "openai_parallel_backend.py")
_TURBO = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "turbo_prompt.py")

MODALITIES = ["CT", "MRI", "SONOGRAPHY", "OBSTETRIC ULTRASOUND",
              "RADIOLOGY", "MAMOGRAPHY", ""]


def _read(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return fh.read()


def _shared_builder():
    """Exec the shared builder out of the source — the module itself is Qt-heavy.
    Same harness as the other prompt guards."""
    src = _read(_REPORTER)
    lines = src.split("\n")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef)
                and n.name == "build_report_system_prompt")
    ns = {"_to_str": lambda x: "" if x is None else str(x),
          "Optional": typing.Optional, "Dict": dict, "Any": object}
    exec(compile("\n".join(lines[node.lineno - 1:node.end_lineno]), _REPORTER, "exec"), ns)
    return ns["build_report_system_prompt"]


def _fn_src(path, name):
    src = _read(path)
    lines = src.split("\n")
    node = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == name)
    return "\n".join(lines[node.lineno - 1:node.end_lineno])


# ── 1. the seam changes nothing yet ──────────────────────────────────────────

@pytest.mark.parametrize("modality", MODALITIES)
@pytest.mark.parametrize("template", ["", "Liver: normal.\nSpleen: normal."])
def test_turbo_prompt_is_byte_identical_to_the_shared_one(modality, template):
    """Phase 1 contract. When this test starts failing ON PURPOSE, that is the gating
    change landing — and it should be the only thing in that diff."""
    from modules.EchoMind.viewer_chat.turbo_prompt import build_turbo_system_prompt
    shared = _shared_builder()
    got = build_turbo_system_prompt(modality, template)
    assert got is not None, "Turbo's builder returned None with the kill switch off"
    assert got == shared(modality, template), (
        f"Turbo's prompt for {modality!r} differs from the shared prompt; phase 1 is "
        "supposed to be a pure refactor"
    )


def test_the_kill_switch_reverts_to_the_shared_builder(monkeypatch):
    """Same field-revertible pattern as _prompt_parity_enabled: a live regression must
    be fixable without a rebuild."""
    from modules.EchoMind.viewer_chat import turbo_prompt as tp
    monkeypatch.setenv("AIPACS_TURBO_PROMPT", "0")
    assert tp.build_turbo_system_prompt("CT", "") is None
    for off in ("false", "no", "OFF"):
        monkeypatch.setenv("AIPACS_TURBO_PROMPT", off)
        assert tp.build_turbo_system_prompt("CT", "") is None
    monkeypatch.delenv("AIPACS_TURBO_PROMPT")
    assert tp.build_turbo_system_prompt("CT", "") is not None


def test_a_builder_failure_degrades_instead_of_raising(monkeypatch):
    """None means 'use what you used yesterday'. A broken Turbo prompt must cost a
    divergence, never a report."""
    from modules.EchoMind.viewer_chat import turbo_prompt as tp
    import modules.EchoMind.viewer_chat.openai_reporter as rep
    monkeypatch.setattr(rep, "build_report_system_prompt",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert tp.build_turbo_system_prompt("CT", "") is None


def test_the_profile_hook_exists_for_phase_two():
    """Reserved now so that wiring the gate is a change to turbo_prompt.py ALONE."""
    import inspect
    from modules.EchoMind.viewer_chat.turbo_prompt import build_turbo_system_prompt
    sig = inspect.signature(build_turbo_system_prompt)
    assert "profile" in sig.parameters
    assert sig.parameters["profile"].kind is inspect.Parameter.KEYWORD_ONLY


# ── 2. the split is at the CALL SITE, and Send is not on the other side ─────

def test_reporter_serves_both_buttons_so_the_split_cannot_live_inside_it():
    """THE reason for this architecture. If this ever becomes false, the seam could be
    simplified — but until then, editing reporter()'s prompt would move Send too."""
    src = _read(_PAGES)
    calls = [ln for ln in src.split("\n") if ".reporter(" in ln]
    assert len(calls) == 2, (
        f"expected exactly two reporter() call sites (Turbo and Send), found {len(calls)}"
    )
    turbo = _fn_src(_PAGES, "_on_hq_all_modality_clicked")
    send = _fn_src(_PAGES, "_on_send_chatgpt")
    assert ".reporter(" in turbo and ".reporter(" in send


def test_only_the_turbo_call_site_passes_an_override():
    turbo = _fn_src(_PAGES, "_on_hq_all_modality_clicked")
    send = _fn_src(_PAGES, "_on_send_chatgpt")
    assert "system_prompt_override=" in turbo, "Turbo is not using its own builder"
    assert "build_turbo_system_prompt" in turbo
    assert "system_prompt_override" not in send, (
        "the Send path is passing an override — it must keep the shared prompt"
    )
    assert "turbo_prompt" not in send


def test_the_turbo_call_site_is_swallowed():
    turbo = _fn_src(_PAGES, "_on_hq_all_modality_clicked")
    i = turbo.index("build_turbo_system_prompt")
    seg = turbo[max(0, i - 400):i + 400]
    assert "try:" in seg and "except Exception" in seg
    assert "_turbo_sys = None" in turbo, "no fallback when the Turbo prompt fails"


def test_the_override_defaults_to_none_so_existing_callers_are_unchanged():
    import inspect
    import modules.EchoMind.viewer_chat.openai_reporter as rep
    sig = inspect.signature(rep.reporter)
    p = sig.parameters["system_prompt_override"]
    assert p.default is None
    assert p.kind is inspect.Parameter.KEYWORD_ONLY, (
        "a positional override could be passed by accident from an existing call"
    )


def test_an_empty_override_still_uses_the_shared_builder():
    """None, '' and whitespace all mean 'nothing to override'. A blank system prompt
    would strip every clinical rule and still look like a successful call."""
    body = _fn_src(_REPORTER, "reporter")
    assert "system_prompt_override.strip()" in body
    assert "build_report_system_prompt(modality, normal_template)" in body


# ── 3. the other pipelines are untouched ────────────────────────────────────

def test_the_parallel_backend_does_not_know_about_the_override():
    """Send-on-OpenAI must be byte-identical to yesterday. If it ever needs the
    parameter, that is a new decision, not a side effect."""
    src = _read(_PARALLEL)
    assert "system_prompt_override" not in src
    assert "turbo_prompt" not in src
    assert "build_report_system_prompt(modality, normal_template)" in src


def test_turbo_stays_pinned_to_the_company_backend():
    """The override only exists on openai_reporter.reporter. If TURBO_BACKEND is ever
    repointed at the parallel backend, the call would fail on an unknown keyword — so
    pin the assumption rather than discover it in production."""
    src = _read(_PAGES)
    i = src.index("backend = TURBO_BACKEND")
    seg = src[max(0, i - 600):i + 200]
    assert "PINNED to the company" in seg or "company" in seg
    assert "TURBO_BACKEND" in src


def test_no_other_feature_prompt_was_touched():
    """These features have their own system prompts and must stay out of this change."""
    src = _read(_REPORTER)
    for name in ("build_correction_system_prompt", "standardize",
                 "standard_assist_search", "translate_report",
                 "translate_text_to_persian", "ImageQualityAnalyzer",
                 "BreastExpertAssistant"):
        assert f"def {name}" in src, f"{name} disappeared"
        assert "system_prompt_override" not in _fn_src(_REPORTER, name), (
            f"{name} picked up the Turbo override"
        )
