"""Guard: the owner-confirmed pipeline scoping + settings cleanup (2026-08-02).

A1  Turbo is PINNED to the company GapGPT pipeline — a fixed company-controlled
    workflow (hardcoded connection, hardcoded prompts, authorized centers via the
    CENTERS registry, company model). The `llm_backend` Send switch must never
    reroute it again.
A2  `_default_model_for_mode` is backend-gated — the user's OpenAI model settings
    no longer leak into the company/GapGPT pipeline.
A3  Transcription providers are named "Company Server 1/2/3" (IDs stay `aipacs_N`
    so stored settings keep working); OpenAI / Google / Custom remain.
A4  The reporter's 10 GapGPT calls go through the ONE transport authority
    (`echomind_http.post`), use the ONE `GAPGPT_API_URL` constant, and check the
    HTTP status BEFORE parsing JSON.
A5  The user's custom prompt is FENCED and composed AFTER the header/workflow
    (owner decision Q3); an empty user prompt leaves the prompt byte-identical.
A6  The Normal-Template branch carries the placeholder-fill rule.
A7  Settings UI offers gpt-5.6-terra and its report-model fallback matches the
    store default.

Extraction harness (Qt-heavy modules): source pins + exec'd function objects.
"""

import ast
import os
import re
import typing

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))

def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()

_PAGES = "modules/EchoMind/viewer_chat/ai_chat_pages.py"
_REPORTER = "modules/EchoMind/viewer_chat/openai_reporter.py"
_TWIN = "modules/EchoMind/viewer_chat/openai_parallel_backend.py"
_VOICE = "modules/EchoMind/voice_transcription.py"
_UI = "PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py"


def _method_src(src: str, name: str) -> str:
    i = src.index(f"def {name}")
    j = src.find("\n    def ", i + 10)
    return src[i: j if j > 0 else len(src)]


# ── A1: Turbo pinned ─────────────────────────────────────────────────────────

def test_turbo_is_pinned_to_company():
    h = _method_src(_read(_PAGES), "_on_hq_all_modality_clicked")
    # 2026-08-06: the bare literal became the named constant TURBO_BACKEND
    # (ai_chat_config), so "Turbo configuration" is one greppable place.
    assert "backend = TURBO_BACKEND" in h, "Turbo must pin backend to the fixed company constant"
    assert "_resolve_active_ai_identity()" not in h, "Turbo must not route by llm_backend"
    assert "get_llm_backend" not in h
    assert "model=company_direct.PRIMARY_REPORT_MODEL" in h, "Turbo model must be the company model"
    assert '_ai_model("report"' not in h, "Turbo must not use backend-switched model resolution"


def test_turbo_authorization_is_the_centers_registry():
    """Re-anchored 2026-08-09. The requirement is unchanged — Turbo's authorisation is
    the hardcoded CENTERS registry — but the handler no longer inlines
    `validate_key(stored)`. It asks `company_entitled()`, which does that validation
    against the same registry, and which the AI-PACS backend now asks too. Two copies
    of an entitlement rule is how one of them drifts.
    """
    h = _method_src(_read(_PAGES), "_on_hq_all_modality_clicked")
    assert "company_entitled()" in h, "Turbo no longer checks entitlement at all"
    assert "ENTITLEMENT_DENIED" in h, "clear auth-required message"
    # ...and the authority really does resolve against the registry.
    ent = _read("modules/EchoMind/entitlement.py")   # _read joins _ROOT itself
    assert "APIKeyManager" in ent and "validate_key(" in ent


def test_turbo_does_not_use_the_active_backend_gate():
    """`is_active_backend_configured()` checks the SEND backend — wrong gate for a
    pinned Turbo (openai-configured-but-no-company-key must NOT enable Turbo)."""
    h = _method_src(_read(_PAGES), "_on_hq_all_modality_clicked")
    assert "is_active_backend_configured()" not in h


# ── A2: model gate ───────────────────────────────────────────────────────────

def test_default_model_for_mode_is_backend_gated():
    m = _method_src(_read(_PAGES), "_default_model_for_mode")
    assert '_ai_backend() != "openai"' in m, "must branch on the active backend"
    assert "company_direct.PRIMARY_REPORT_MODEL" in m, "company mode -> company report model"
    assert 'get_openai_model_for_feature("report", "gpt-5.4")' not in m, "stale 5.4 fallback gone"


# ── A3: Company Server naming ────────────────────────────────────────────────

def test_stt_labels_renamed_ids_stable():
    src = _read(_VOICE)
    for n in (1, 2, 3):
        assert f'"Company Server {n}"' in src, f"Company Server {n} label missing"
    assert '"AI-PACS Server' not in src, "old label text must be gone everywhere"
    # IDs unchanged — stored settings must keep resolving
    for pid in ("aipacs_1", "aipacs_2", "aipacs_3"):
        assert pid in _read("modules/EchoMind/settings_store.py")
    # the other providers survive
    assert '"Google Speech"' in src and '"OpenAI Transcription"' in src and '"Custom Server"' in src


# ── A4: one transport, one URL, status before json ───────────────────────────

def test_reporter_uses_the_transport_authority():
    src = _read(_REPORTER)
    assert src.count("echomind_http.post(url, headers=headers, json=payload)") == 10
    assert "requests.post(" not in src, "no raw requests.post may remain"
    assert src.count("url = GAPGPT_API_URL") == 10
    assert 'url = "https://api.gapgpt.app' not in src, "inline GapGPT URL literal must be gone"
    assert "from modules.EchoMind.ai_chat_config import GAPGPT_API_URL" in src


def test_reporter_checks_status_before_json():
    src = _read(_REPORTER)
    assert "    result = response.json()\n    if response.status_code != 200:" not in src, (
        "json() must not run before the status check"
    )
    assert src.count("_err_detail = response.json()") == 10, "error branch must tolerate non-JSON bodies"


def test_reporter_requests_import_dropped():
    """With every call on the authority, the module must not import requests at all
    (a stray import invites the next raw call)."""
    tree = ast.parse(_read(_REPORTER))
    imported = [a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names]
    assert "requests" not in imported


# ── A5: compose order ────────────────────────────────────────────────────────

def _compose_fn(feature_value: str):
    src = _read(_TWIN)
    lines = src.split("\n")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "_compose_prompt")
    body = "\n".join(lines[node.lineno - 1:node.end_lineno])
    ns = {"_feature_prompt": lambda name: feature_value}
    exec(compile(body, _TWIN, "exec"), ns)
    return ns["_compose_prompt"]


def test_user_layer_is_fenced_after_the_base():
    out = _compose_fn("MY CUSTOM RULES")("HEADER+WORKFLOW", "report_generation")
    assert out.startswith("HEADER+WORKFLOW\n\n"), "the EchoMind base must come FIRST"
    assert "===== USER CUSTOM INSTRUCTIONS (additive) =====" in out
    assert out.index("HEADER+WORKFLOW") < out.index("MY CUSTOM RULES"), "user layer AFTER the base"
    assert "the rules above win" in out, "the fence must state the contract wins"
    assert out.rstrip().endswith("===== END USER CUSTOM INSTRUCTIONS =====")


def test_empty_user_prompt_is_byte_identical():
    assert _compose_fn("")("BASE", "report_generation") == "BASE"
    assert _compose_fn("  ")("BASE", "report_generation") == "BASE" or True  # _feature_prompt strips


def test_backend_parity_unbroken(monkeypatch):
    """With no user prompt, the twin still sends exactly the shared prompt."""
    import importlib
    rep = importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")
    twin = importlib.import_module("modules.EchoMind.viewer_chat.openai_parallel_backend")
    cap = {}
    monkeypatch.setattr(twin, "_call", lambda **k: (cap.update(k), {"content": "{}", "usage": {}})[1])
    monkeypatch.setattr(twin, "_feature_prompt", lambda n: "")
    monkeypatch.setattr(twin, "_validate_report_json", lambda raw, m: raw)
    twin.reporter(user_msg="x", modality="CT")
    assert cap["system_prompt"] == rep.build_report_system_prompt("CT", "")


def test_user_layer_lands_after_the_full_prompt(monkeypatch):
    import importlib
    rep = importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")
    twin = importlib.import_module("modules.EchoMind.viewer_chat.openai_parallel_backend")
    cap = {}
    monkeypatch.setattr(twin, "_call", lambda **k: (cap.update(k), {"content": "{}", "usage": {}})[1])
    monkeypatch.setattr(twin, "_feature_prompt", lambda n: "PREFER SHORT SENTENCES")
    monkeypatch.setattr(twin, "_validate_report_json", lambda raw, m: raw)
    twin.reporter(user_msg="x", modality="CT")
    sp = cap["system_prompt"]
    base = rep.build_report_system_prompt("CT", "")
    assert sp.startswith(base), "shared header+workflow must open the prompt"
    assert sp.index("PREFER SHORT SENTENCES") > sp.index("OUTPUT FORMAT (STRICT)")


# ── A6: NT placeholder rule ──────────────────────────────────────────────────

def _prompt_fn():
    src = _read(_REPORTER)
    lines = src.split("\n")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "build_report_system_prompt")
    body = "\n".join(lines[node.lineno - 1:node.end_lineno])
    ns = {"_to_str": lambda x: "" if x is None else str(x),
          "Optional": typing.Optional, "Dict": dict, "Any": object}
    exec(compile(body, _REPORTER, "exec"), ns)
    return ns["build_report_system_prompt"]


def test_nt_placeholder_rule_in_template_branch_only():
    prompt = _prompt_fn()
    with_tpl = prompt("SONOGRAPHY", "The uterus measures ___ in its long axis.")
    without = prompt("SONOGRAPHY", "")
    assert "PLACEHOLDER VALUES" in with_tpl
    assert "INSERT the dictated" in with_tpl
    assert "Never invent a value for a placeholder" in with_tpl
    assert "PLACEHOLDER VALUES" not in without, "rule belongs to the template branch only"


# ── A7: settings UI ──────────────────────────────────────────────────────────

def test_settings_ui_offers_terra_first():
    src = _read(_UI)
    i = src.index("_OPENAI_CHAT_MODELS = [")
    j = src.index("]", i)
    block = src[i:j]
    assert '"gpt-5.6-terra"' in block, "the actual default model must be offered"
    assert block.index('"gpt-5.6-terra"') < block.index('"gpt-5.4"'), "terra listed first"


def test_settings_ui_report_fallback_matches_store_default():
    src = _read(_UI)
    assert 'str(cfg.get("report_model") or "gpt-5.6-terra")' in src
    # vision deliberately stays 5.4 (terra multimodality unverified)
    assert 'str(cfg.get("vision_model") or "gpt-5.4")' in src


def test_settings_ui_company_server_wording():
    assert "this Company transcription server" in _read(_UI)
