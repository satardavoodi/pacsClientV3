"""Guard: Turbo is a FIXED company workflow the end user cannot reconfigure
(owner directive 2026-08-06).

Turbo spends the company's paid LLM budget on the company's GapGPT account, so
every knob is in-code and none of it is reachable from Settings ▸ EchoMind:

    provider  -> TURBO_BACKEND        (ai_chat_config, hardcoded "company")
    endpoint  -> GAPGPT_API_URL       (ai_chat_config, hardcoded)
    model     -> PRIMARY_REPORT_MODEL (openai_reporter, hardcoded constant)
    prompt    -> build_report_system_prompt (in-code, per modality)
    who may   -> the hardcoded CENTERS registry (api_manager)

The regression these tests exist to stop: `llm_backend` used to reroute Turbo, so
flipping the SEND backend to the user's own OpenAI silently moved Turbo onto the
user's key, model and endpoint. `llm_backend` is a SEND-backend switch ONLY.
"""

import ast
import os
import re

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


_CONFIG = "modules/EchoMind/ai_chat_config.py"
_PAGES = "modules/EchoMind/viewer_chat/ai_chat_pages.py"
_UI = "PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py"


def _turbo_handler() -> str:
    src = _read(_PAGES)
    i = src.index("def _on_hq_all_modality_clicked")
    j = src.find("\n    def ", i + 10)
    return src[i: j if j > 0 else len(src)]


# ── the configuration is in code, and named ──────────────────────────────────

def test_turbo_constants_exist_and_are_fixed():
    cfg = _read(_CONFIG)
    assert 'TURBO_BACKEND = "company"' in cfg, "Turbo must be pinned to the company provider"
    assert "TURBO_USER_CONFIGURABLE = False" in cfg, "the invariant flag must stay False"


def test_turbo_user_configurable_is_false():
    """If anyone ever flips this, they must confront these tests."""
    cfg = _read(_CONFIG)
    m = re.search(r"TURBO_USER_CONFIGURABLE\s*=\s*(\w+)", cfg)
    assert m and m.group(1) == "False"


def test_handler_uses_the_named_constant():
    h = _turbo_handler()
    assert "backend = TURBO_BACKEND" in h
    assert 'backend = "company"' not in h, "use the named constant, not a bare literal"


# ── nothing user-configurable may reach the Turbo path ───────────────────────

_SETTINGS_READERS = [
    "get_llm_backend",
    "get_openai_settings",
    "get_openai_model_for_feature",
    "get_prompt_settings",
    "_resolve_active_ai_identity",
    "_ai_model",
    "_ai_backend",
    "is_active_backend_configured",
]


@pytest.mark.parametrize("reader", _SETTINGS_READERS)
def test_turbo_handler_reads_no_user_setting(reader):
    h = _turbo_handler()
    assert reader not in h, (
        f"Turbo must not consult {reader}() — that is a user-configurable value and "
        "Turbo is a fixed company workflow"
    )


def test_turbo_model_is_the_hardcoded_company_constant():
    h = _turbo_handler()
    assert "model=company_direct.PRIMARY_REPORT_MODEL" in h
    # not a settings-derived model
    assert "get_openai_model_for_feature" not in h


def test_turbo_authorization_is_the_hardcoded_registry():
    h = _turbo_handler()
    assert "APIKeyManager" in h, "authorization comes from the hardcoded CENTERS registry"
    assert "validate_key" in h
    assert "Turbo requires an authorized company key" in h


# ── the Settings UI offers no Turbo knob ─────────────────────────────────────

def test_settings_ui_has_no_turbo_field():
    """Turbo deliberately has NO Settings presence — adding one would make the
    company's LLM budget user-configurable."""
    ui = _read(_UI)
    live = [ln for ln in ui.split("\n")
            if "turbo" in ln.lower() and not ln.lstrip().startswith("#")]
    assert not live, f"a Turbo control appeared in Settings: {live[:3]}"


def test_settings_store_has_no_turbo_key():
    store = _read("modules/EchoMind/settings_store.py")
    live = [ln for ln in store.split("\n")
            if "turbo" in ln.lower() and not ln.lstrip().startswith("#")]
    assert not live, f"a persisted Turbo setting appeared: {live[:3]}"


# ── the endpoint and prompt are in-code ──────────────────────────────────────

def test_turbo_endpoint_and_prompt_are_in_code():
    rep = _read("modules/EchoMind/viewer_chat/openai_reporter.py")
    assert "from modules.EchoMind.ai_chat_config import GAPGPT_API_URL" in rep
    assert rep.count("url = GAPGPT_API_URL") >= 1, "endpoint from the hardcoded constant"
    assert "def build_report_system_prompt" in rep, "prompt is built in-code"
    # the company report path must not compose a user prompt into it
    i = rep.index("def reporter(")
    j = rep.index("\ndef ", i + 10)
    assert "_compose_prompt" not in rep[i:j], "no user-prompt layer on the company path"


def test_llm_backend_is_documented_as_send_only():
    cfg = _read(_CONFIG)
    assert "SEND backend only" in cfg or "selects the SEND backend" in cfg
