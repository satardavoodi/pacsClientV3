"""Guard: the two EchoMind AI backends must not be two different products.

Background (2026-08-01)
-----------------------
EchoMind has two interchangeable implementations of the same feature set, chosen
by ONE setting (Settings ▸ EchoMind ▸ backend), dispatched through
``ai_chat_pages._ai_module()``:

  * ``company`` -> ``openai_reporter``            (GapGPT)
  * ``openai``  -> ``openai_parallel_backend``    (provider-aware)

The prompt-stack review found they were **not** the same product:

  * ``openai_parallel_backend.reporter()`` sent a ~1,100-character generic
    prompt whose entire modality handling was ``prompt += f"\\nModality:
    {modality}."``. No BI-RADS rules, no Persian/Finglish term maps, no
    per-region normal templates, no never-presume rule, no temperature clamp,
    no output validation. So flipping a settings toggle silently changed
    CLINICAL CONTENT — the same dictation produced a materially different
    report, and the radiologist had no way to know which prompt they got.
  * ``openai_parallel_backend.correction()`` still hard-coded the fixed 5-key
    schema, which DELETES a mammogram's BI-RADS category, breast composition
    and axillary evaluation (and invents an empty Impression) the moment a
    physician corrects a typo. Removing exactly that from the company path was
    the point of the KEY-SET MIRROR rule.

Both now call the ONE authority in ``openai_reporter``. These tests fail if
anyone re-forks them.
"""

import ast
import importlib
import os

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_VIEWER_CHAT = os.path.normpath(
    os.path.join(_THIS, "..", "..", "..", "modules", "EchoMind", "viewer_chat")
)
_REPORTER_PY = os.path.join(_VIEWER_CHAT, "openai_reporter.py")
_TWIN_PY = os.path.join(_VIEWER_CHAT, "openai_parallel_backend.py")

# The exact strings the modality button can send (ai_chat_pages).
_UI_MODALITIES = ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY"]


def _src(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _fn_source(path: str, name: str) -> str:
    src = _src(path)
    lines = src.split("\n")
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"top-level def {name} not found in {path}")


@pytest.fixture()
def reporter_mod():
    return importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")


@pytest.fixture()
def twin(monkeypatch):
    """The OpenAI backend with its transport stubbed; returns (module, capture)."""
    mod = importlib.import_module("modules.EchoMind.viewer_chat.openai_parallel_backend")
    cap: dict = {}

    def _fake_call(**kw):
        cap.update(kw)
        return {"content": '{"Report Title":"t"}', "usage": {"total_tokens": 1}}

    monkeypatch.setattr(mod, "_call", _fake_call)
    # A per-feature Settings prompt would be prepended to the system prompt; blank
    # it so these tests compare the prompt the CODE builds, not the operator's extra.
    monkeypatch.setattr(mod, "_feature_prompt", lambda name: "")
    # These tests assert what the backend SENDS. The real validator would reject
    # the one-key stub above (correctly — see
    # `test_the_twin_fails_loudly_on_an_incomplete_report`, which restores it), so
    # pass it through here rather than build a valid report per modality.
    monkeypatch.setattr(mod, "_validate_report_json", lambda raw, m: raw)
    return mod, cap


# ─────────────────────────────────────────────────────────────────────────────
# 1. The sampling clamp is one decision, not two
# ─────────────────────────────────────────────────────────────────────────────

def test_sampling_helper_matches_the_literals_reporter_pins(reporter_mod):
    """`report_sampling_params` and `reporter()`'s inline payload lines agree.

    `reporter()` keeps its two literal assignments because four tests source-pin
    them; this asserts the shared helper the twin uses can never drift from
    those literals.
    """
    body = _fn_source(_REPORTER_PY, "reporter")
    assert 'payload["temperature"] = 0.1' in body
    assert 'payload["max_tokens"] = 2500' in body
    assert reporter_mod.report_sampling_params("CT") == {"temperature": 0.1, "max_tokens": 2500}


def test_every_ui_modality_gets_the_clamp(reporter_mod):
    for ui in _UI_MODALITIES:
        assert reporter_mod.report_sampling_params(ui).get("temperature") == 0.1, (
            f"{ui!r} (a value the modality button really sends) has no temperature clamp"
        )


def test_an_unvalidated_modality_gets_no_clamp(reporter_mod):
    for other in ("Fluoroscopy", "PET", "", None):
        assert reporter_mod.report_sampling_params(other) == {}


# ─────────────────────────────────────────────────────────────────────────────
# 2. The report prompt is byte-identical across backends
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("modality", _UI_MODALITIES)
def test_both_backends_send_the_same_report_system_prompt(modality, twin, reporter_mod):
    mod, cap = twin
    mod.reporter(user_msg="findings.", modality=modality)
    assert cap["system_prompt"] == reporter_mod.build_report_system_prompt(modality, ""), (
        f"the OpenAI backend sends a DIFFERENT prompt for {modality!r} — a settings "
        f"toggle would change clinical content"
    )


def test_the_normal_template_reaches_the_shared_prompt(twin, reporter_mod):
    mod, cap = twin
    tpl = "Liver normal. Prostate unremarkable."
    mod.reporter(user_msg="abdomen.", modality="CT", normal_template=tpl)
    assert tpl in cap["system_prompt"]
    assert cap["system_prompt"] == reporter_mod.build_report_system_prompt("CT", tpl)


@pytest.mark.parametrize("modality", _UI_MODALITIES)
def test_the_twin_applies_the_temperature_clamp(modality, twin):
    mod, cap = twin
    mod.reporter(user_msg="findings.", modality=modality)
    assert cap.get("temperature") == 0.1, (
        f"{modality!r} runs at the Settings temperature on the OpenAI backend — the "
        f"company path pins 0.1 for every structure-validated modality"
    )


def test_the_twin_leaves_max_tokens_to_settings(twin):
    """Deliberate difference, documented in `reporter()`'s docstring.

    On this backend the output budget also has to cover REASONING tokens, so
    imposing the company path's hard 2500 could truncate a report the company
    path renders fine.
    """
    mod, cap = twin
    mod.reporter(user_msg="findings.", modality="CT")
    assert cap.get("max_tokens") in (None, 0), (
        "the twin should not force the company path's 2500-token cap"
    )


def test_the_generic_modality_line_is_only_in_the_legacy_path():
    """`prompt += f"\\nModality: {modality}."` was the ENTIRE modality handling."""
    twin_src = _src(_TWIN_PY)
    needle = 'prompt += f"\\nModality: {modality}."'
    assert needle in twin_src, "legacy path should still exist behind the kill switch"
    assert needle in _fn_source(_TWIN_PY, "_legacy_reporter"), (
        "the generic one-line modality handling escaped back into the live path"
    )
    assert needle not in _fn_source(_TWIN_PY, "reporter")


def test_the_live_reporter_calls_the_shared_authority():
    body = _fn_source(_TWIN_PY, "reporter")
    assert "build_report_system_prompt(" in body
    assert "report_sampling_params(" in body
    assert "_validate_report_json(" in body


# ─────────────────────────────────────────────────────────────────────────────
# 3. Output validation runs on BOTH backends
# ─────────────────────────────────────────────────────────────────────────────

def test_the_twin_validates_its_report_output(twin, monkeypatch):
    mod, cap = twin
    seen = {}

    def _fake_validate(raw, modality):
        seen["raw"] = raw
        seen["modality"] = modality
        return raw

    monkeypatch.setattr(mod, "_validate_report_json", _fake_validate)
    mod.reporter(user_msg="findings.", modality="MAMOGRAPHY")
    assert seen.get("modality") == "mamography", "validation must receive the lower-cased modality"


def test_the_twin_fails_loudly_on_an_incomplete_report(twin, monkeypatch, reporter_mod):
    """The REAL validator, on the REAL twin path.

    Before 2026-08-01 this backend never validated at all, so a mammography
    report missing its BI-RADS category rendered as if complete. Now it raises,
    exactly like the company path — the caller's error branch shows the failure
    instead of a report with a hole in it.
    """
    mod, _cap = twin
    monkeypatch.setattr(mod, "_validate_report_json", reporter_mod._validate_report_json)
    with pytest.raises(ValueError, match="Required key missing or empty"):
        mod.reporter(user_msg="findings.", modality="CT")


def test_validation_kill_switch_is_honoured_on_the_twin(twin, monkeypatch):
    mod, _cap = twin
    called = []
    monkeypatch.setattr(mod, "_validate_report_json", lambda raw, m: called.append(m) or raw)
    monkeypatch.setattr(mod, "_report_validation_enabled", lambda: False)
    mod.reporter(user_msg="findings.", modality="CT")
    assert called == [], "AIPACS_ECHOMIND_REPORT_VALIDATION=0 must disable it on both backends"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Correction: no fixed key schema anywhere
# ─────────────────────────────────────────────────────────────────────────────

def test_the_twin_correction_uses_the_shared_prompt(twin, reporter_mod):
    mod, cap = twin
    mod.correction(user_report='{"Report Title":"x"}', correction_note="fix", target_section="")
    assert cap["system_prompt"] == reporter_mod.build_correction_system_prompt()
    assert cap["feature_name"] == "correction"
    assert cap["temperature"] == 0


def test_the_twin_correction_payload_matches_the_company_payload(twin, reporter_mod):
    mod, cap = twin
    mod.correction(user_report="{}", correction_note="n", target_section="S")
    assert cap["user_content"] == reporter_mod.build_correction_user_content("{}", "n", "S")
    assert "===== TARGET_LOCATION" in cap["user_content"]


def test_no_fixed_key_schema_survives_in_either_backend():
    """The sentence that deleted BI-RADS. It may appear only as documentation."""
    for path in (_REPORTER_PY, _TWIN_PY):
        src = _src(path)
        code_only = "\n".join(
            l for l in src.splitlines() if not l.lstrip().startswith("#")
        )
        for banned in (
            "Return ONLY valid JSON with keys Report Title, Pathological Findings, "
            "Normal Findings, Impression, Recommendations",
            "EXACTLY these 5 keys",
        ):
            assert banned not in code_only, (
                f"{os.path.basename(path)} still imposes a fixed key set: {banned!r}"
            )


def test_the_correction_prompt_has_no_leftover_five_key_instruction(reporter_mod):
    """The HTML-input branch used to say 'convert to the required 5-key JSON schema',
    which contradicted the KEY-SET MIRROR rule three paragraphs below it."""
    sp = reporter_mod.build_correction_system_prompt()
    assert "KEY-SET MIRROR" in sp
    assert "5-key JSON schema" not in sp
    assert "5-key JSON baseline" not in sp
    # and the rules that replaced it are intact
    for rule in (
        "the SAME top-level keys as ORIGINAL_REPORT",
        "Adding a section that did not exist is a FAILURE",
        "Persian in, Persian out",
        "Changes Made",
    ):
        assert rule in sp, f"correction prompt lost: {rule!r}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. The shared builders stay pure and reachable
# ─────────────────────────────────────────────────────────────────────────────

def test_the_prompt_builder_is_pure():
    """No network, no Manage, no settings read — that is what makes it shareable
    and unit-testable, and what lets the twin call it without a GapGPT key."""
    body = _fn_source(_REPORTER_PY, "build_report_system_prompt")
    for banned in ("requests.", "Manage.instance", "get_openai_settings", "chat_completion"):
        assert banned not in body, f"prompt builder reached for {banned!r}"


def test_both_backends_expose_the_same_feature_surface():
    company = importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")
    openai_side = importlib.import_module("modules.EchoMind.viewer_chat.openai_parallel_backend")
    for fn in (
        "reporter", "correction", "chat", "standardize", "standard_assist_search",
        "translate_text_to_persian", "translate_report", "BreastExpertAssistant",
        "ImageQualityAnalyzer",
    ):
        assert callable(getattr(company, fn, None)), f"openai_reporter.{fn} missing"
        assert callable(getattr(openai_side, fn, None)), f"openai_parallel_backend.{fn} missing"


def test_kill_switch_restores_the_legacy_generic_prompt(twin, monkeypatch):
    mod, cap = twin
    monkeypatch.setenv("AIPACS_ECHOMIND_BACKEND_PROMPT_PARITY", "0")
    mod.reporter(user_msg="findings.", modality="CT")
    sp = cap["system_prompt"]
    assert "You are EchoMind report generation." in sp
    assert "Modality: CT." in sp
    assert len(sp) < 4000, "kill switch should send the small legacy prompt"
    assert cap.get("temperature") is None, "the legacy path had no temperature clamp"


def test_parity_is_on_by_default(twin, monkeypatch):
    mod, cap = twin
    monkeypatch.delenv("AIPACS_ECHOMIND_BACKEND_PROMPT_PARITY", raising=False)
    assert mod._prompt_parity_enabled() is True
    mod.reporter(user_msg="findings.", modality="CT")
    assert len(cap["system_prompt"]) > 20000, "default must be the full shared prompt"
