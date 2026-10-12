"""The default backend must need no configuration, and must not be configurable away.

Two promises are under test:

* A clinic that picks «هوش مصنوعی ایران نوبت» has a working assistant with
  nothing entered — so validation must not demand a key, and the model must come
  from the build rather than from a settings file that could name a retired one.
* Choosing one backend must not leak the other's credentials. The single
  ``llm_api_key`` field belongs to OpenAI; exporting it as the company key would
  override the bundled one and fail every request with an auth error.
"""

from __future__ import annotations

import os

import pytest

from reception_crm import secrets as secret_store
from reception_crm.connections import MobileInternalLlmConnection
from reception_crm.llm import client, company_backend, config

LLM_ENV = (
    "RECEPTION_LLM_API_KEY",
    "RECEPTION_LLM_BACKEND",
    "RECEPTION_LLM_MODEL",
    "RECEPTION_OPENAI_API_KEY",
    "RECEPTION_OPENAI_BASE_URL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture(autouse=True)
def portable_secrets(monkeypatch):
    """Make the secret store reversible off-Windows.

    Real storage is DPAPI, which only exists on Windows and raises rather than
    ever writing plaintext. These tests are about which key goes where, not
    about the encryption, so a transparent stand-in keeps them runnable on any
    machine while leaving the production path untouched.
    """
    monkeypatch.setattr(secret_store, "is_available", lambda: True)
    monkeypatch.setattr(secret_store, "protect", lambda value: f"test:{value}" if value else "")
    monkeypatch.setattr(
        secret_store, "unprotect", lambda value: value[5:] if str(value).startswith("test:") else (value or "")
    )


# --------------------------------------------------------------------------- #
# the company backend is fixed by the build
# --------------------------------------------------------------------------- #
def test_company_is_the_default_backend():
    assert config.backend() == "company"


def test_company_uses_the_build_model_when_nothing_overrides_it(monkeypatch):
    """A clinic configures nothing and gets the model this build was tested with."""
    monkeypatch.delenv("RECEPTION_LLM_MODEL", raising=False)
    assert config.model() == company_backend.MODEL


def test_an_explicit_override_wins_on_the_company_backend_too(monkeypatch):
    """Reversal of an earlier decision, on purpose, with the reason recorded.

    This used to be `test_company_model_ignores_user_settings`, guarding against
    a stale settings file naming a retired model and breaking the assistant with
    nothing to explain why. That risk is real.

    But the cure had a worse failure of its own: `llm.model` is a field the
    installer asks the operator to fill in, `server.json` stores, and `describe`
    prints back — and on this backend it did **nothing**. It happened to read
    the same value the build used, so the two agreed by coincidence, and the day
    they diverged `describe` would have confidently named a model the server was
    not calling.

    The override now wins and is *reported*: `public_dict()` publishes the
    effective model, and `warnings()` says out loud when a config value is
    overriding the build. Visible-and-changeable beats invisible-and-fixed.
    """
    monkeypatch.setenv("RECEPTION_LLM_MODEL", "gpt-5.4-mini")
    assert config.model() == "gpt-5.4-mini"


def test_the_override_is_never_silent(monkeypatch, tmp_path):
    """The guard that makes the reversal safe. If this stops warning, the
    original objection — a stale file breaking the assistant invisibly — comes
    straight back."""
    from reception_crm.server import config as server_config

    cfg = server_config.ServerConfig(
        center="RAZI",
        data_root=tmp_path,
        llm=server_config.LlmConfig(api_key="x", model="gpt-5.4-mini"),
        reception=server_config.ReceptionConfig(username="u", password="p"),
    )
    notes = "\n".join(cfg.warnings())
    assert "gpt-5.4-mini" in notes
    assert company_backend.MODEL in notes, "the note must name what is being overridden"


def test_the_build_default_produces_no_override_warning(tmp_path):
    from reception_crm.server import config as server_config

    cfg = server_config.ServerConfig(
        center="RAZI",
        data_root=tmp_path,
        llm=server_config.LlmConfig(api_key="x"),  # model unset = build default
        reception=server_config.ReceptionConfig(username="u", password="p"),
    )
    assert not any("override" in note.lower() for note in cfg.warnings())


def test_openai_model_does_honour_user_settings(monkeypatch):
    monkeypatch.setenv("RECEPTION_LLM_BACKEND", "openai")
    monkeypatch.setenv("RECEPTION_LLM_MODEL", "gpt-4o")
    assert config.model() == "gpt-4o"


def test_transport_constants_come_from_one_place():
    assert config.GAPGPT_API_URL == company_backend.API_URL
    assert config.GAPGPT_DEFAULT_MODEL == company_backend.MODEL


def test_environment_key_wins_over_everything(monkeypatch):
    monkeypatch.setenv("RECEPTION_LLM_API_KEY", "sk-from-env")
    assert company_backend.api_key(stored="sk-stored") == "sk-from-env"
    assert company_backend.status()["source"] == "environment"


def test_stored_key_is_the_last_resort(monkeypatch):
    monkeypatch.setattr(company_backend, "bundled_key", lambda: "")
    assert company_backend.api_key(stored="sk-stored") == "sk-stored"
    assert company_backend.status(stored="sk-stored")["source"] == "stored"


def test_placeholder_key_file_does_not_count_as_configured(tmp_path, monkeypatch):
    """A developer checkout must not look like a packaged build."""
    placeholder = tmp_path / company_backend.KEY_FILE_NAME
    placeholder.write_text("<REPLACE_WITH_IRAN_NOBAT_KEY>\n", encoding="utf-8")
    monkeypatch.setattr(company_backend, "_candidate_key_files", lambda: (placeholder,))
    assert company_backend.bundled_key() == ""
    assert not company_backend.is_available()


def test_real_key_file_is_picked_up(tmp_path, monkeypatch):
    real = tmp_path / company_backend.KEY_FILE_NAME
    real.write_text("  sk-real-key  \n", encoding="utf-8")
    monkeypatch.setattr(company_backend, "_candidate_key_files", lambda: (real,))
    assert company_backend.bundled_key() == "sk-real-key"
    assert company_backend.is_available()
    assert company_backend.status()["source"] == "bundled"


def test_status_never_reveals_the_key(monkeypatch):
    monkeypatch.setenv("RECEPTION_LLM_API_KEY", "sk-secret-value-here")
    status = company_backend.status()
    assert "sk-secret-value-here" not in str(status)
    assert status["length"] == str(len("sk-secret-value-here"))


def test_missing_key_says_it_is_a_packaging_fault(monkeypatch):
    monkeypatch.setattr(company_backend, "bundled_key", lambda: "")
    with pytest.raises(client.LLMNoKeyError) as caught:
        client.resolve_backend()
    # The clinic cannot fix this; the message must not ask them to.
    assert "company_key.txt" in str(caught.value)


def test_resolved_session_uses_the_company_endpoint(monkeypatch):
    monkeypatch.setenv("RECEPTION_LLM_API_KEY", "sk-x")
    session = client.resolve_backend()
    assert session.provider == "company"
    assert session.api_url == company_backend.API_URL
    assert session.display_name == company_backend.DISPLAY_NAME


# --------------------------------------------------------------------------- #
# validation follows the chosen backend
# --------------------------------------------------------------------------- #
def test_company_backend_needs_no_key_from_the_user():
    section = MobileInternalLlmConnection(enabled=True)
    assert section.validate() == []


def test_openai_backend_does_need_a_key():
    section = MobileInternalLlmConnection(enabled=True, llm_backend="openai")
    errors = section.validate()
    assert any("OpenAI" in error for error in errors)


def test_openai_backend_with_a_key_validates():
    section = MobileInternalLlmConnection(
        enabled=True, llm_backend="openai", llm_api_key=secret_store.protect("sk-user")
    )
    assert not any("OpenAI" in error for error in section.validate())


def test_unknown_backend_is_rejected():
    section = MobileInternalLlmConnection(enabled=True, llm_backend="something-else")
    assert any("بک‌اند" in error for error in section.validate())


def test_uses_company_backend_property():
    assert MobileInternalLlmConnection().uses_company_backend is True
    assert MobileInternalLlmConnection(llm_backend="openai").uses_company_backend is False


# --------------------------------------------------------------------------- #
# switching backends must not leak credentials between them
# --------------------------------------------------------------------------- #
def test_company_backend_never_exports_the_users_openai_key(monkeypatch):
    """The regression this guards: an OpenAI key left over from an earlier
    choice being exported as the company key, overriding the bundled one."""
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    section = MobileInternalLlmConnection(
        enabled=True, llm_backend="company", llm_api_key=secret_store.protect("sk-users-openai-key")
    )
    section.apply_env()
    assert os.environ.get("RECEPTION_LLM_API_KEY", "") == ""
    assert "RECEPTION_OPENAI_API_KEY" not in os.environ


def test_switching_to_company_clears_stale_openai_settings(monkeypatch):
    monkeypatch.setenv("RECEPTION_OPENAI_API_KEY", "sk-old")
    monkeypatch.setenv("RECEPTION_OPENAI_BASE_URL", "https://old.example")
    MobileInternalLlmConnection(llm_backend="company").apply_env()
    assert "RECEPTION_OPENAI_API_KEY" not in os.environ
    assert "RECEPTION_OPENAI_BASE_URL" not in os.environ


def test_openai_backend_exports_its_own_key(monkeypatch):
    section = MobileInternalLlmConnection(
        enabled=True, llm_backend="openai", llm_api_key=secret_store.protect("sk-mine")
    )
    section.apply_env()
    assert os.environ["RECEPTION_OPENAI_API_KEY"] == "sk-mine"


def test_company_backend_does_not_export_a_model(monkeypatch):
    MobileInternalLlmConnection(llm_backend="company", llm_model="stale-model").apply_env()
    assert os.environ["RECEPTION_LLM_MODEL"] == ""
