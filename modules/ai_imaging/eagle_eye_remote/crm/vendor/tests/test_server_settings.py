"""The installer-written configuration: LLM, reception, and the local host rule.

Every test here exists because the setting it covers is one an operator sets
once, on a clinical server, and then never looks at again. A silent default is
worse than a crash.
"""

from __future__ import annotations

import json
import os

import pytest

from reception_crm import local_host
from reception_crm.server.config import (
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_MODEL,
    DEFAULT_RECEPTION_PORT,
    ServerConfig,
    apply_to_environment,
    load_server_config,
    write_default_config,
)

_MANAGED_ENV = (
    "RECEPTION_LLM_BACKEND",
    "RECEPTION_LLM_API_KEY",
    "RECEPTION_LLM_MODEL",
    "RECEPTION_LLM_TIMEOUT",
    "RECEPTION_LLM_TEMPERATURE",
    "RECEPTION_LLM_MAX_TOKENS",
    "RECEPTION_LLM_PROXY",
    "RECEPTION_OPENAI_API_KEY",
    "RECEPTION_OPENAI_BASE_URL",
    "INO_HOST",
    "INO_CRM_PORT",
    "INO_USER",
    "INO_PASS",
    "RECEPTION_LOCAL_HOST",
    "RECEPTION_SESSION_SECRET",
    "RECEPTION_HTTP_API_TOKEN",
    "RECEPTION_HTTP_API_CENTER",
    "RECEPTION_CRM_DATA_ROOT",
    "RECEPTION_CRM_CONFIG_DIR",
    "RECEPTION_CENTER_CONFIG_PATH",
)


@pytest.fixture(autouse=True)
def clean_env():
    from reception_crm.lexicon import center

    saved = {name: os.environ.get(name) for name in _MANAGED_ENV}
    for name in _MANAGED_ENV:
        os.environ.pop(name, None)
    local_host.reset_cache()
    center.reset_cache()
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    local_host.reset_cache()
    center.reset_cache()


def _write(tmp_path, payload: dict) -> "os.PathLike[str]":
    target = tmp_path / "server.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


# --------------------------------------------------------------------------- #
# LLM section
# --------------------------------------------------------------------------- #
def test_llm_settings_come_from_the_config_file(tmp_path):
    path = _write(
        tmp_path,
        {
            "llm": {
                "provider": "openai",
                "api_key": "sk-from-file",
                "base_url": "https://example.invalid/v1",
                "model": "some-model",
                "timeout": 30,
                "temperature": 0.4,
                "max_tokens": 900,
                "proxy": "socks5://127.0.0.1:2080",
            }
        },
    )
    config = load_server_config(path)

    assert config.llm.provider == "openai"
    assert config.llm.api_key == "sk-from-file"
    assert config.llm.base_url == "https://example.invalid/v1"
    assert config.llm.model == "some-model"
    assert config.llm.timeout == 30
    assert config.llm.temperature == 0.4
    assert config.llm.max_tokens == 900
    assert config.llm.proxy == "socks5://127.0.0.1:2080"


def test_config_written_by_an_older_installer_still_loads(tmp_path):
    """The installer never rewrites an existing server.json, so upgrades arrive
    with no `llm` or `reception` block at all. That must not be fatal."""
    path = _write(tmp_path, {"bind": "all", "port": 8770, "session_secret": "x" * 40})
    config = load_server_config(path)

    assert config.llm.provider == "company"
    assert config.llm.model == DEFAULT_LLM_MODEL
    assert config.llm.max_tokens == DEFAULT_LLM_MAX_TOKENS
    assert config.llm.api_key == ""
    assert config.reception.port == DEFAULT_RECEPTION_PORT
    assert config.validate() == []


def test_a_wrongly_typed_section_does_not_crash_the_loader(tmp_path):
    path = _write(tmp_path, {"llm": "company", "reception": ["8080"]})
    config = load_server_config(path)
    assert config.llm.provider == "company"
    assert config.reception.port == DEFAULT_RECEPTION_PORT


def test_environment_still_overrides_the_file(tmp_path):
    """Same precedence as every other field: env wins, so an operator can
    override on a dev box without editing the installed config."""
    path = _write(tmp_path, {"llm": {"model": "from-file", "api_key": "sk-file"}})
    os.environ["RECEPTION_LLM_MODEL"] = "from-env"
    config = load_server_config(path)
    assert config.llm.model == "from-env"
    assert config.llm.api_key == "sk-file"


def test_unconfigured_llm_warns_but_does_not_block_startup(tmp_path):
    config = load_server_config(_write(tmp_path, {}))
    assert config.validate() == []
    assert any("llm.api_key is empty" in note for note in config.warnings())


def test_bad_provider_is_a_blocking_problem(tmp_path):
    config = load_server_config(_write(tmp_path, {"llm": {"provider": "anthropic"}}))
    assert any("llm.provider" in problem for problem in config.validate())


def test_llm_key_reaches_the_environment_the_client_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(local_host, "resolve_reception_host", lambda port, **_: "10.0.0.9")
    config = load_server_config(
        _write(tmp_path, {"llm": {"provider": "company", "api_key": "sk-company"}})
    )
    apply_to_environment(config)

    assert os.environ["RECEPTION_LLM_API_KEY"] == "sk-company"
    assert os.environ["RECEPTION_LLM_BACKEND"] == "company"
    # Empty means "explicitly direct", so it must be SET, not merely absent --
    # otherwise a machine-level HTTP_PROXY silently captures LLM traffic.
    assert os.environ["RECEPTION_LLM_PROXY"] == ""


def test_openai_provider_uses_the_openai_variables(tmp_path, monkeypatch):
    monkeypatch.setattr(local_host, "resolve_reception_host", lambda port, **_: "10.0.0.9")
    config = load_server_config(
        _write(
            tmp_path,
            {"llm": {"provider": "openai", "api_key": "sk-oa", "base_url": "https://x.invalid/v1"}},
        )
    )
    apply_to_environment(config)

    assert os.environ["RECEPTION_OPENAI_API_KEY"] == "sk-oa"
    assert os.environ["RECEPTION_OPENAI_BASE_URL"] == "https://x.invalid/v1"
    assert "RECEPTION_LLM_API_KEY" not in os.environ


def test_public_dict_never_shows_the_key(tmp_path):
    config = load_server_config(_write(tmp_path, {"llm": {"api_key": "sk-secret-value"}}))
    rendered = json.dumps(config.public_dict())
    assert "sk-secret-value" not in rendered
    assert config.public_dict()["llm"]["api_key_set"] is True


# --------------------------------------------------------------------------- #
# Reception section — the host is NOT a setting
# --------------------------------------------------------------------------- #
def test_reception_section_has_no_host_field():
    """The agent is installed ON the reception server. A host field would let
    one clinic's install be pointed at another clinic's reception server."""
    assert not hasattr(ServerConfig().reception, "host")
    assert "host" not in ServerConfig().reception.__dataclass_fields__


def test_written_template_offers_a_port_but_never_a_host(tmp_path):
    path = write_default_config(tmp_path / "server.json")
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["reception"]["port"] == DEFAULT_RECEPTION_PORT
    assert "host" not in written["reception"]


def test_reception_credentials_reach_the_upstream_client_variables(tmp_path, monkeypatch):
    monkeypatch.setattr(local_host, "resolve_reception_host", lambda port, **_: "192.0.2.7")
    config = load_server_config(
        _write(tmp_path, {"reception": {"port": 8081, "username": "svc", "password": "pw"}})
    )
    apply_to_environment(config)

    assert os.environ["INO_HOST"] == "192.0.2.7"
    assert os.environ["INO_CRM_PORT"] == "8081"
    assert os.environ["INO_USER"] == "svc"
    assert os.environ["INO_PASS"] == "pw"


def test_apply_environment_switches_resolver_from_seed_to_generated_center(
    tmp_path, monkeypatch
):
    from reception_crm.lexicon import center

    generated = tmp_path / "center_config.json"
    generated.write_text(
        json.dumps({"center": "TEST", "departments": [], "services": [], "service_concepts": []}),
        encoding="utf-8",
    )
    monkeypatch.setenv("RECEPTION_CRM_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(local_host, "resolve_reception_host", lambda port, **_: "10.0.0.9")

    center.reset_cache()
    assert center.load_center().get("center") == "RAZI", "source process starts on its seed"

    apply_to_environment(ServerConfig(center="TEST", data_root=tmp_path))

    assert center.load_center().get("center") == "TEST"


def test_out_of_range_reception_port_is_blocking(tmp_path):
    config = load_server_config(_write(tmp_path, {"reception": {"port": 70000}}))
    assert any("reception.port" in problem for problem in config.validate())


# --------------------------------------------------------------------------- #
# Local host resolution
# --------------------------------------------------------------------------- #
def test_override_wins_and_skips_probing(monkeypatch):
    monkeypatch.setenv("RECEPTION_LOCAL_HOST", "10.1.2.3")
    monkeypatch.setattr(
        local_host, "_auth_route_exists", lambda *a, **k: pytest.fail("must not probe")
    )
    assert local_host.resolve_reception_host(8080) == "10.1.2.3"


def test_picks_the_address_where_the_auth_route_actually_answers(monkeypatch):
    """The whole point: the vendor API answers /api/auth/login with 404 on
    loopback but 401 on the machine's own LAN address. Picking the wrong one
    means reads work, login never does, and it looks like a mobile bug."""
    monkeypatch.setattr(local_host, "local_ipv4_addresses", lambda: ["10.0.0.5", "192.168.1.222"])
    monkeypatch.setattr(
        local_host, "_auth_route_exists", lambda host, port: host == "192.168.1.222"
    )
    assert local_host.resolve_reception_host(8080) == "192.168.1.222"


def test_falls_back_to_loopback_rather_than_crashing(monkeypatch):
    monkeypatch.setattr(local_host, "local_ipv4_addresses", lambda: ["10.0.0.5"])
    monkeypatch.setattr(local_host, "_auth_route_exists", lambda host, port: False)
    assert local_host.resolve_reception_host(8080) == local_host.LOOPBACK


def test_result_is_cached_per_port(monkeypatch):
    calls: list[str] = []

    def probe(host, port):
        calls.append(host)
        return True

    monkeypatch.setattr(local_host, "local_ipv4_addresses", lambda: ["10.0.0.5"])
    monkeypatch.setattr(local_host, "_auth_route_exists", probe)

    local_host.resolve_reception_host(8080)
    local_host.resolve_reception_host(8080)
    assert calls == ["10.0.0.5"], "the install location does not change mid-process"


def test_loopback_is_never_offered_as_a_candidate(monkeypatch):
    monkeypatch.setattr(local_host, "_primary_ipv4", lambda: "")
    monkeypatch.setattr(
        local_host.socket,
        "gethostbyname_ex",
        lambda _: ("host", [], ["127.0.0.1", "169.254.1.1", "10.0.0.5"]),
    )
    assert local_host.local_ipv4_addresses() == ["10.0.0.5"]


# --------------------------------------------------------------------------- #
# Regression: the previously silent packaging failure
# --------------------------------------------------------------------------- #
def test_both_llm_prompts_exist_on_disk():
    """A missing prompt used to be a 500 in front of a clinician. The spec now
    refuses to build without them; this catches a delete before the build does."""
    from reception_crm.llm import interpreter

    assert interpreter.PROMPT_PATH.exists(), interpreter.PROMPT_PATH
    assert interpreter.ANALYSIS_PROMPT_PATH.exists(), interpreter.ANALYSIS_PROMPT_PATH


def test_logs_follow_the_configured_data_root(tmp_path, monkeypatch):
    """Logging is configured before apply_to_environment() runs, so it used to
    resolve log_root() from the hard-coded default data root. On the reception
    server that silently created a stray D:\\RAZI crm and hid the service log
    inside it."""
    import logging as _logging

    from reception_crm.server.runner import LOG_FILENAME, configure_logging

    configured = tmp_path / "Reception CRM Data"
    config = ServerConfig(data_root=configured)

    saved_handlers = list(_logging.getLogger().handlers)
    try:
        log_file = configure_logging(config)
    finally:
        for handler in list(_logging.getLogger().handlers):
            handler.close()
            _logging.getLogger().removeHandler(handler)
        for handler in saved_handlers:
            _logging.getLogger().addHandler(handler)

    assert log_file == configured / "logs" / LOG_FILENAME
    assert log_file.parent.exists()
    assert os.environ["RECEPTION_CRM_DATA_ROOT"] == str(configured)


def test_truncated_analysis_payload_says_so():
    """Whenever data is dropped on the way to the model, the model is told.

    This used to assert the word "TRUNCATED" and a payload LONGER than the
    limit, because the only way to shrink a payload was to slice the JSON string
    and append a note. There is now a better path for the common case — a
    display row list is trimmed to a sample and replaced with a count — so an
    oversized result comes back UNDER the limit and still valid JSON.

    The property the test defends is unchanged: nothing is dropped silently.
    Both paths are checked, so neither can regress into quiet loss.
    """
    from reception_crm.llm.interpreter import MAX_ANALYSIS_PAYLOAD_CHARS, build_analysis_payload

    small = build_analysis_payload({"a": 1})
    assert "TRUNCATED" not in small
    assert "_omitted" not in small

    # A row list: trimmed, so it now FITS, and says how many were left out.
    rows = build_analysis_payload({"rows": ["x" * 100] * 500})
    assert len(rows) <= MAX_ANALYSIS_PAYLOAD_CHARS
    assert "rows_omitted" in rows
    assert "500" in rows, "the real count has to survive, not just the sample"

    # Anything else oversized is compacted structurally.  It must stay valid
    # JSON and explicitly say that compaction happened; a cut fragment can make
    # every later field disappear while looking plausible to a model.
    blob = build_analysis_payload({"blob": {"k%d" % i: "v" * 60 for i in range(500)}})
    restored = json.loads(blob)
    assert len(blob) <= MAX_ANALYSIS_PAYLOAD_CHARS
    assert restored["payloadCompacted"] is True
    assert restored["data"]["blob"]["_omittedKeys"] == 470
