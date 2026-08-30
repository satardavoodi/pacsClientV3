"""Guard: EchoMind failures must be DISTINGUISHABLE, and still redacted (F2).

THE DEFECT: `_safe_fa_connection_error` had two return branches that emitted the
same "check your internet connection" sentence, and `ApiWorker.run` routes every
exception through it — so `LLMAuthError` / `LLMAPIError HTTP 429` / "no API key
configured" all reached the physician as a network complaint. Switching servers
or LLMs was undiagnosable.

Two properties are pinned here and they pull against each other:
  1. the endpoint/credential is NEVER leaked (the reason the function exists);
  2. the CAUSE is preserved (the reason this fix exists).

The module is imported normally (`ai_chat_helpers` uses a relative import, so it
must be loaded as part of its real package). NOTE: this test deliberately does
NOT install a `sys.modules["PySide6"] = ModuleType(...)` stub — that permanent,
un-restored stubbing in `test_gapgpt_connection.py` is exactly what made
`test_test_server.py` un-collectable in a directory run.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture(scope="module")
def H():
    return importlib.import_module("modules.EchoMind.viewer_chat.ai_chat_helpers")


# ── 1. The cause survives ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected_kind",
    [
        # Exactly what llm_client.py raises, verbatim in shape.
        ("No OpenAI API key is configured. Open Settings -> EchoMind -> OpenAI.", "no_key"),
        ("No EchoMind credential is configured. Open Settings -> EchoMind and authenticate.", "no_key"),
        ("OpenAI rejected the request. Check the configured API key.", "auth"),
        ("OpenAI HTTP 401: {'error': {'message': 'Incorrect API key provided'}}", "auth"),
        ("EchoMind HTTP 403: forbidden", "auth"),
        ("OpenAI HTTP 429: rate limit reached for gpt-5.4", "quota"),
        ("OpenAI HTTP 404: not found", "model"),
        ("EchoMind HTTP 500: upstream failure", "server"),
        ("OpenAI HTTP 400: invalid request body", "bad_request"),
        ("Malformed response: missing choices.", "malformed"),
        ("Malformed response body: Expecting value: line 1 column 1 (char 0)", "malformed"),
        ("The model `gpt-9` does not exist or you do not have access to it", "model"),
        ("401 Client Error: Unauthorized for url: /v1/chat/completions", "auth"),
    ],
)
def test_each_failure_mode_is_classified(H, raw, expected_kind):
    kind, text = H.classify_echomind_error(raw)
    assert kind == expected_kind, f"{raw!r} -> {kind} (text={text!r})"


def test_a_real_transport_failure_still_gets_the_legacy_network_text(H):
    raw = (
        "HTTPSConnectionPool(host='api.openai.com', port=443): Max retries exceeded "
        "with url: /v1/chat/completions (Caused by NewConnectionError(...))"
    )
    kind, text = H.classify_echomind_error(raw)
    assert kind == "network"
    # Byte-identical to the pre-fix sentence — that message was already correct.
    assert text == H._LEGACY_NETWORK_TEXT


def test_the_four_headline_causes_are_mutually_distinguishable(H):
    """The whole point: these must NOT all render as the same sentence."""
    texts = {
        H._safe_fa_connection_error("No OpenAI API key is configured."),
        H._safe_fa_connection_error("OpenAI HTTP 401: bad key"),
        H._safe_fa_connection_error("OpenAI HTTP 429: quota exceeded"),
        H._safe_fa_connection_error(
            "HTTPSConnectionPool(host='x', port=443): Max retries exceeded"
        ),
    }
    assert len(texts) == 4, f"causes collapsed to {len(texts)} message(s): {texts}"


def test_network_advice_is_not_given_for_a_credential_problem(H):
    """The specific regression: an auth failure told the user to check the internet."""
    text = H._safe_fa_connection_error("OpenAI HTTP 401: Incorrect API key provided")
    assert "internet connection" not in text.lower()
    assert "api key" in text.lower()


# ── 2. Redaction is preserved (the property the old function existed for) ────

_KEY_REDACTION_FIXTURE = "s" + "k-redaction-fixture"


@pytest.mark.parametrize(
    "secret, raw",
    [
        ("api.openai.com", "OpenAI HTTP 500: failed calling https://api.openai.com/v1/chat/completions"),
        ("80.210.31.214", "EchoMind HTTP 500: upstream 80.210.31.214:8085 refused"),
        (_KEY_REDACTION_FIXTURE, f"EchoMind HTTP 400: bad key {_KEY_REDACTION_FIXTURE}"),
        ("api.gapgpt.app", "Network error contacting EchoMind: https://api.gapgpt.app/v1/chat/completions"),
    ],
)
def test_no_endpoint_or_credential_ever_reaches_the_user(H, secret, raw):
    text = H._safe_fa_connection_error(raw)
    assert secret not in text, f"leaked {secret!r} in: {text!r}"


def test_bearer_tokens_are_redacted(H):
    out = H._redact_endpoint_details("headers={'Authorization': 'Bearer abc123secret'}")
    assert "abc123secret" not in out
    assert "<key>" in out


def test_redaction_bounds_the_detail_length(H):
    out = H._redact_endpoint_details("x" * 5000)
    assert len(out) <= 200


# ── 3. Kill switch + never-raise ─────────────────────────────────────────────

def test_flag_off_restores_byte_identical_legacy_behaviour(H, monkeypatch):
    monkeypatch.setenv("AIPACS_ECHOMIND_ERROR_DETAIL", "0")
    assert H._safe_fa_connection_error("OpenAI HTTP 401: bad key") == H._LEGACY_FALLBACK_TEXT
    assert (
        H._safe_fa_connection_error("HTTPSConnectionPool(host='x'): Max retries exceeded")
        == H._LEGACY_NETWORK_TEXT
    )


def test_flag_on_is_the_default(H, monkeypatch):
    monkeypatch.delenv("AIPACS_ECHOMIND_ERROR_DETAIL", raising=False)
    assert H.error_detail_enabled() is True


@pytest.mark.parametrize("raw", [None, "", 0, [], {"a": 1}])
def test_never_raises_on_any_input(H, raw):
    assert isinstance(H._safe_fa_connection_error(raw), str)


def test_output_is_always_non_empty(H):
    for raw in (None, "", "boom", "OpenAI HTTP 401"):
        assert H._safe_fa_connection_error(raw).strip()
