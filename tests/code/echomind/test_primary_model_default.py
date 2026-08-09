"""Guard: report-processing runs on gpt-5.6-terra (2026-08-02).

Physician directive: report generation, the Normal Template workflow, correction,
standardization and report translation all move to gpt-5.6-terra — newer, stronger
at instruction-following, and cheaper than the previous mix (gpt-4.1-mini for
reports, gpt-5.4 for correction). One name, one place, env-overridable.

These are source/behaviour pins so a future edit can't silently drop a
report-processing function back to a mini model — which is what the customer's
Turbo report was actually running on.
"""

import ast
import importlib
import os

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))


def _reporter_src():
    p = os.path.normpath(os.path.join(
        _THIS, "..", "..", "..", "modules", "EchoMind", "viewer_chat", "openai_reporter.py"))
    with open(p, encoding="utf-8") as fh:
        return fh.read(), p


def _model_default(tree, name):
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    if not fn.args.defaults:
        return None
    for arg, default in zip(fn.args.args[-len(fn.args.defaults):], fn.args.defaults):
        if arg.arg == "model":
            return ast.unparse(default)
    return None


def test_the_primary_model_is_terra():
    src, _ = _reporter_src()
    assert 'PRIMARY_REPORT_MODEL = (os.environ.get("AIPACS_ECHOMIND_PRIMARY_MODEL") or "gpt-5.6-terra")' in src


@pytest.mark.parametrize("fn", [
    "reporter", "correction", "standardize", "standard_assist_search", "translate_report",
])
def test_report_processing_fn_defaults_to_the_primary_model(fn):
    src, _ = _reporter_src()
    assert _model_default(ast.parse(src), fn) == "PRIMARY_REPORT_MODEL", (
        f"{fn}() must default to PRIMARY_REPORT_MODEL, not a hard-coded model string"
    )


@pytest.mark.parametrize("fn", ["chat", "ImageQualityAnalyzer", "BreastExpertAssistant"])
def test_non_report_functions_are_left_alone(fn):
    """Chat / vision / breast are not report generation — they must NOT have been
    swept into the report-model change."""
    src, _ = _reporter_src()
    assert _model_default(ast.parse(src), fn) != "PRIMARY_REPORT_MODEL"


def test_env_override_is_honoured(monkeypatch):
    monkeypatch.setenv("AIPACS_ECHOMIND_PRIMARY_MODEL", "gpt-5.6-sol")
    mod = importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")
    importlib.reload(mod)
    try:
        assert mod.PRIMARY_REPORT_MODEL == "gpt-5.6-sol"
    finally:
        monkeypatch.delenv("AIPACS_ECHOMIND_PRIMARY_MODEL", raising=False)
        importlib.reload(mod)
    assert mod.PRIMARY_REPORT_MODEL == "gpt-5.6-terra"


def test_settings_store_report_model_default_is_terra():
    from modules.EchoMind import settings_store as ss
    src = __import__("inspect").getsource(ss)
    assert '"openai_report_model": "gpt-5.6-terra"' in src
    # vision is intentionally NOT moved (terra may not be multimodal) — it keeps 5.4
    assert '"openai_vision_model": "gpt-5.4"' in src


def test_standardize_and_translation_follow_the_report_model_on_openai():
    """On the OpenAI backend, Standard and report translation move with
    report/correction (terra), not with chat (text_model)."""
    from modules.EchoMind import settings_store as ss
    src = __import__("inspect").getsource(ss)
    assert '"standardize": "report_model"' in src
    assert '"translation": "report_model"' in src
    # chat/assist/search stay on text_model
    assert '"chat": "text_model"' in src
