"""Provider selection must never invent a direct endpoint or a medical model."""
import json

import pytest


@pytest.fixture
def settings(tmp_path, monkeypatch):
    from modules.EchoMind import settings_store
    path = tmp_path / "echomind_settings.json"
    monkeypatch.setattr(settings_store, "_config_path", lambda: path)
    settings_store._invalidate_settings_cache()
    yield settings_store
    settings_store._invalidate_settings_cache()


def test_fresh_install_uses_company_without_direct_endpoint(settings):
    assert settings.get_llm_backend() == "company"
    assert settings.get_openai_settings()["base_url"] == ""


@pytest.mark.parametrize("missing", ["openai_api_key", "openai_base_url"])
def test_incomplete_legacy_direct_selection_uses_company(settings, missing):
    data = {"llm_backend": "openai", "openai_api_key": "synthetic-key",
            "openai_base_url": "https://provider.invalid/v1"}
    data.pop(missing)
    settings.save_settings(data)
    assert settings.get_llm_backend() == "company"


def test_saved_credentials_alone_do_not_select_direct(settings):
    settings.save_openai_settings({"api_key": "synthetic-key", "base_url": "https://provider.invalid/v1"})
    assert settings.get_llm_backend() == "company"


def test_complete_explicit_direct_choice_is_preserved(settings):
    settings.save_settings({"llm_backend": "openai", "openai_api_key": "synthetic-key",
                            "openai_base_url": "https://provider.invalid/v1"})
    assert settings.get_llm_backend() == "openai"


def test_saving_blank_endpoint_does_not_supply_one(settings):
    settings.save_openai_settings({"api_key": "synthetic-key", "base_url": ""})
    assert settings.get_openai_settings()["base_url"] == ""


@pytest.mark.parametrize("feature", ["eagle_eye", "eagle_eye_screening", "eagle_eye_verification"])
def test_missing_direct_eagle_model_cannot_use_company_default(settings, feature):
    with pytest.raises(ValueError, match="Eagle Eye"):
        settings.get_openai_model_for_feature(feature, "company-only-model")


def test_explicit_eagle_models_round_trip(settings):
    settings.save_openai_settings({"eagle_eye_model": "chosen-diagnosis", "eagle_eye_screening_model": "chosen-screen"})
    assert settings.get_openai_model_for_feature("eagle_eye") == "chosen-diagnosis"
    assert settings.get_openai_model_for_feature("eagle_eye_screening") == "chosen-screen"
    settings.save_openai_settings({"base_url": "https://provider.invalid/v1"})
    assert settings.get_openai_model_for_feature("eagle_eye") == "chosen-diagnosis"


def test_key_override_cannot_switch_company_route(monkeypatch):
    from modules.EchoMind import llm_client
    sentinel = object()
    monkeypatch.setattr(llm_client, "_active_backend", lambda: "company")
    monkeypatch.setattr(llm_client, "_resolve_company_backend", lambda: sentinel)
    monkeypatch.setattr(llm_client, "_resolve_openai_backend", lambda **kw: pytest.fail("implicit direct route"))
    assert llm_client._resolve_active_backend(api_key_override="synthetic-key") is sentinel


def test_direct_resolver_requires_explicit_endpoint(monkeypatch):
    from modules.EchoMind import llm_client
    monkeypatch.setattr(llm_client, "get_openai_settings", lambda: {"api_key": "synthetic-key"})
    with pytest.raises(llm_client.LLMError, match="[Bb]ase URL"):
        llm_client._resolve_openai_backend()


def test_connection_probe_cannot_invent_endpoint(monkeypatch):
    from modules.EchoMind import llm_client
    monkeypatch.setattr(llm_client.echomind_http, "get", lambda *a, **kw: pytest.fail("network must not be reached"))
    with pytest.raises(llm_client.LLMError, match="[Bb]ase URL"):
        llm_client.test_openai_connection(api_key="synthetic-key")


def test_explicit_direct_endpoint_reaches_transport(settings, monkeypatch):
    from modules.EchoMind import llm_client
    settings.save_settings({"llm_backend": "openai", "openai_api_key": "synthetic-key",
                            "openai_base_url": "https://provider.invalid/v1"})
    session = llm_client._resolve_active_backend()
    assert session.provider == "openai"
    assert session.api_url == "https://provider.invalid/v1/chat/completions"


def test_eagle_resolver_does_not_swallow_missing_direct_model(settings, monkeypatch):
    from modules.ai_imaging.eagle_eye_lumbar import llm_backend, analysis_prompt
    for name in ["AIPACS_EAGLE_EYE_MODEL", "AIPACS_EAGLE_EYE_SCREENING_MODEL"]:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(llm_backend.AnalysisUnavailable, match="Eagle Eye"):
        llm_backend.resolve_model("openai", analysis_prompt.LUMBAR_SCREENING)


def test_company_eagle_model_defaults_remain_available(settings, monkeypatch):
    from modules.ai_imaging.eagle_eye_lumbar import llm_backend, analysis_prompt
    for name in ["AIPACS_EAGLE_EYE_MODEL", "AIPACS_EAGLE_EYE_SCREENING_MODEL"]:
        monkeypatch.delenv(name, raising=False)
    stage = analysis_prompt.LUMBAR_SCREENING
    assert llm_backend.resolve_model("company", stage) == stage.model_default


def test_bundled_settings_cannot_seed_direct_endpoint():
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parents[3] / "config/echomind_settings.json").read_text(encoding="utf-8"))
    assert data["llm_backend"] == "company"
    endpoint_present = bool(data.get("openai_base_url"))
    del data
    assert not endpoint_present


def test_transcription_requires_explicit_endpoint_before_reading_audio(monkeypatch):
    from modules.EchoMind.secretary.stt.providers import openai_transcribe
    monkeypatch.setattr(openai_transcribe, "get_openai_settings", lambda: {"api_key": "synthetic-key"})
    monkeypatch.setattr(openai_transcribe, "get_openai_model_for_feature", lambda *a: "synthetic-model")
    result = openai_transcribe.OpenAITranscribeProvider().transcribe_files([])
    assert not result["ok"]
    assert "base url" in result["error"].lower()


def test_runner_reports_model_configuration_failure_without_starting_worker(settings, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_lumbar import llm_backend, llm_runner, analysis_store
    monkeypatch.setattr(llm_runner.llm_package, "build_package", lambda *a, **kw: SimpleNamespace(analysis=None))
    monkeypatch.setattr(llm_backend, "resolve_backend", lambda: "openai")
    def missing(*args):
        raise llm_backend.AnalysisUnavailable("Choose Eagle Eye models")
    monkeypatch.setattr(llm_backend, "resolve_stage_models", missing)
    runner = llm_runner.EagleEyeAnalysisRunner(tmp_path)
    failures = []
    runner.failed.connect(failures.append)
    assert runner.start() is False
    assert failures == ["Choose Eagle Eye models"]
    assert not runner.running
    assert analysis_store.read_record(tmp_path).state == analysis_store.STATE_FAILED


def _settings_method(name, namespace=None):
    """Execute the UI slot without constructing account-detecting widgets."""
    import ast
    import typing
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    context = {"t": typing, **(namespace or {})}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), context)
    return context[name]


def test_settings_form_preserves_explicit_eagle_models_and_blank_endpoint():
    from types import SimpleNamespace
    def field(value):
        return SimpleNamespace(text=lambda: value, currentText=lambda: value,
                               currentData=lambda: value, value=lambda: value)
    form = SimpleNamespace()
    for name in ("api_key", "base_url", "org", "project", "text_model", "report_model",
                 "vision_model", "secretary_model", "transcription_model"):
        setattr(form, "openai_" + name + "_input", field(""))
    form.openai_eagle_screening_input = field("chosen-screen")
    form.openai_eagle_diagnosis_input = field("chosen-diagnosis")
    form.openai_reasoning_combo = field("")
    for name in ("temperature", "max_tokens", "timeout"):
        setattr(form, "openai_" + name + "_spin", field(30))
    patch = _settings_method("_openai_form_patch")(form)
    assert patch["eagle_eye_screening_model"] == "chosen-screen"
    assert patch["eagle_eye_model"] == "chosen-diagnosis"
    assert patch["base_url"] == ""


def test_settings_ui_cannot_activate_unsaved_direct_configuration():
    from types import SimpleNamespace
    notices = []
    method = _settings_method("_on_save_backend_clicked", {
        "get_openai_settings": lambda: {},
        "set_llm_backend": lambda *a: pytest.fail("incomplete direct mode activated"),
        "QMessageBox": SimpleNamespace(warning=lambda *a: notices.append(a[-1])),
    })
    method(SimpleNamespace(backend_combo=SimpleNamespace(currentData=lambda: "openai")))
    assert len(notices) == 1
