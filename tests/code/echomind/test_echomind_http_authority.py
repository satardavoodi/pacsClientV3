"""Guard: ONE transport authority for every EchoMind call (F3 + F6).

THE DEFECT: EchoMind made the same two transport decisions — which proxy, what
timeout — independently at 19 call sites and got different answers.

  * `llm_client.py` and `openai_reporter.py` each carried a private copy of
    `_get_requests_proxies()` and passed `proxies=` everywhere.
  * The four chat modes (URL_CHAT / URL_GEN_REPORT / URL_GEN_ASSISTANT /
    URL_SEARCH), every voice-to-text upload, and the OpenAI STT provider passed
    NOTHING — so Settings ▸ EchoMind's "all EchoMind API calls are tunnelled
    through the local proxy" was false for half the module, and `direct` did not
    actually bypass a Windows/env proxy for those calls (requests defaults to
    trust_env=True).
  * Timeouts ranged over 60 / 180 / 300 / 360 s, only one path had a fast
    connect timeout, and the same feature got 180 s on the company backend but
    60 s on OpenAI.

`modules/EchoMind/echomind_http.py` is now the single authority. These tests are
what stops a future call site from quietly re-forking the decision.

SCOPE NOTE: the reception/RIS calls in `ai_chat_pages._send_with_patient_id` are
intentionally excluded — they target the hospital's own reception server, not an
EchoMind AI endpoint, and forcing them down an AI-provisioned SOCKS5 tunnel
would break a working local integration.
"""
from __future__ import annotations

import ast
import importlib
import os
import re

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_ECHOMIND = os.path.join(_ROOT, "modules", "EchoMind")


@pytest.fixture(scope="module")
def H():
    return importlib.import_module("modules.EchoMind.echomind_http")


def _read(*parts: str) -> str:
    with open(os.path.join(_ECHOMIND, *parts), encoding="utf-8") as fh:
        return fh.read()


# ── 1. no bare requests call survives in the AI / voice paths ────────────────

#: Files that must contain ZERO bare `requests.<verb>(` calls.
#: `echomind_http.py` is excluded by construction — it IS the wrapper.
_AI_PATH_FILES = [
    ("voice_transcription.py", 0),
    (os.path.join("secretary", "stt", "providers", "openai_transcribe.py"), 0),
    ("llm_client.py", 0),
]

_BARE_CALL_RE = re.compile(r"\brequests\.(get|post|put|delete|patch|request)\s*\(")


@pytest.mark.parametrize("relpath, allowed", _AI_PATH_FILES)
def test_no_unrouted_requests_call_in_the_ai_paths(relpath, allowed):
    src = _read(relpath)
    found = _BARE_CALL_RE.findall(src)
    assert len(found) == allowed, (
        f"{relpath}: {len(found)} bare requests.* call(s), expected {allowed}. "
        "Route it through modules.EchoMind.echomind_http so the Settings proxy "
        "and the connect/read timeout split are applied."
    )


def test_the_four_chat_modes_go_through_the_authority():
    """URL_CHAT / URL_GEN_REPORT / URL_GEN_ASSISTANT / URL_SEARCH."""
    src = _read("viewer_chat", "ai_chat_pages.py")
    for url_const in ("URL_CHAT", "URL_GEN_REPORT", "URL_GEN_ASSISTANT", "URL_SEARCH"):
        assert f"echomind_http.post({url_const}" in src, (
            f"{url_const} is not posted through echomind_http — it will ignore "
            "the Settings connection type (this was the F3 defect)"
        )
        assert f"requests.post({url_const}" not in src, (
            f"{url_const} still has a bare requests.post — that is the defect"
        )


def test_the_reception_calls_are_deliberately_left_alone():
    """Documents the scope decision so nobody 'fixes' it by accident."""
    src = _read("viewer_chat", "ai_chat_pages.py")
    assert "requests.get(validate_url" in src
    assert "reception" in src.lower()


# ── 2. exactly one implementation of the proxy decision ──────────────────────

def test_only_the_authority_builds_a_socks_proxy_dict():
    offenders = []
    for dirpath, _dirs, files in os.walk(_ECHOMIND):
        if "__pycache__" in dirpath:
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            if os.path.basename(path) == "echomind_http.py":
                continue
            with open(path, encoding="utf-8") as fh:
                if "socks5://127.0.0.1" in fh.read():
                    offenders.append(os.path.relpath(path, _ROOT))
    assert not offenders, (
        f"duplicate proxy construction in {offenders} — delegate to "
        "echomind_http.requests_proxies() instead of re-deriving it"
    )


@pytest.mark.parametrize(
    "module_name",
    ["modules.EchoMind.llm_client", "modules.EchoMind.viewer_chat.openai_reporter"],
)
def test_legacy_helper_names_still_exist_and_delegate(module_name):
    """Call sites/tests reference `_get_requests_proxies` — keep the name."""
    mod = importlib.import_module(module_name)
    assert hasattr(mod, "_get_requests_proxies")


# ── 3. proxy semantics ───────────────────────────────────────────────────────

def test_direct_returns_empty_dict_not_none(H, monkeypatch):
    """{} bypasses system/env proxies; None would let them apply."""
    monkeypatch.setattr(
        H, "get_proxy_settings",
        lambda: {"connection_type": "direct", "proxy_port": 2080},
    )
    assert H.requests_proxies() == {}


def test_socks5_returns_the_configured_local_proxy(H, monkeypatch):
    monkeypatch.setattr(
        H, "get_proxy_settings",
        lambda: {"connection_type": "socks5", "proxy_port": 2081},
    )
    proxies = H.requests_proxies()
    assert proxies == {
        "http": "socks5://127.0.0.1:2081",
        "https": "socks5://127.0.0.1:2081",
    }


def test_proxy_resolution_never_raises(H, monkeypatch):
    def _boom():
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr(H, "get_proxy_settings", _boom)
    assert H.requests_proxies() == {}


def test_proxy_kill_switch_returns_none(H, monkeypatch):
    monkeypatch.setenv("AIPACS_ECHOMIND_PROXY_AUTHORITY", "0")
    assert H.requests_proxies() is None
    assert H.proxy_authority_enabled() is False


def test_proxy_authority_is_on_by_default(H, monkeypatch):
    monkeypatch.delenv("AIPACS_ECHOMIND_PROXY_AUTHORITY", raising=False)
    assert H.proxy_authority_enabled() is True


# ── 4. timeout semantics (F6) ────────────────────────────────────────────────

def test_default_timeout_is_a_connect_read_tuple_not_a_scalar(H, monkeypatch):
    monkeypatch.delenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", raising=False)
    assert H.resolve_timeout() == (10.0, 180.0)


def test_a_scalar_from_a_caller_is_upgraded_to_fail_fast_on_connect(H, monkeypatch):
    """A bare 300 used to mean a 300 s CONNECT wait on a dead host."""
    monkeypatch.delenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", raising=False)
    connect, read = H.resolve_timeout(300)
    assert connect == 10.0
    assert read == 300.0


def test_a_short_caller_timeout_is_respected_on_both_phases(H, monkeypatch):
    monkeypatch.delenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", raising=False)
    assert H.resolve_timeout(8) == (8.0, 8.0)


def test_upload_read_budget_is_longer_than_a_chat_completion(H):
    assert H.UPLOAD_READ_TIMEOUT_S > H.DEFAULT_READ_TIMEOUT_S


def test_timeout_kill_switch_restores_the_legacy_hang(H, monkeypatch):
    monkeypatch.setenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", "0")
    assert H.resolve_timeout() is None
    assert H.resolve_timeout(300) is None


def test_env_override_sets_the_read_budget(H, monkeypatch):
    monkeypatch.setenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", "45")
    assert H.resolve_timeout() == (10.0, 45.0)


def test_openai_read_budget_now_matches_the_company_backend(H):
    """The F6 asymmetry: same feature, 180 s on company vs 60 s on OpenAI."""
    from modules.EchoMind import settings_store

    assert settings_store._defaults()["openai_timeout_seconds"] == int(
        H.DEFAULT_READ_TIMEOUT_S
    )


def test_openai_reporter_timeout_helper_delegates():
    from modules.EchoMind.viewer_chat import openai_reporter

    assert openai_reporter._request_timeout() == (10.0, 180.0)


# ── 5. the wrappers actually apply the policy ────────────────────────────────

class _FakeResponse:
    status_code = 200


def test_post_injects_proxies_and_timeout(H, monkeypatch):
    seen = {}

    def _fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return _FakeResponse()

    monkeypatch.delenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", raising=False)
    monkeypatch.delenv("AIPACS_ECHOMIND_PROXY_AUTHORITY", raising=False)
    monkeypatch.setattr(H.requests, "post", _fake_post)
    monkeypatch.setattr(
        H, "get_proxy_settings", lambda: {"connection_type": "direct", "proxy_port": 2080}
    )

    H.post("http://example/x", json={"a": 1})
    assert seen["proxies"] == {}
    assert seen["timeout"] == (10.0, 180.0)
    assert seen["json"] == {"a": 1}


def test_an_explicit_proxies_argument_is_not_overridden(H, monkeypatch):
    seen = {}
    monkeypatch.setattr(H.requests, "get", lambda url, **kw: (seen.update(kw), _FakeResponse())[1])
    H.get("http://example/x", proxies={"http": "socks5://127.0.0.1:9999"})
    assert seen["proxies"] == {"http": "socks5://127.0.0.1:9999"}


def test_wrappers_pass_files_and_headers_through(H, monkeypatch):
    seen = {}
    monkeypatch.setattr(H.requests, "post", lambda url, **kw: (seen.update(kw), _FakeResponse())[1])
    H.post("http://example/x", files={"file": ("a.wav", b"x", "audio/wav")}, headers={"A": "b"})
    assert "files" in seen and seen["headers"] == {"A": "b"}


def test_socks_preflight_is_a_noop_without_socks(H):
    H.ensure_socks_support(None)
    H.ensure_socks_support({})
    H.ensure_socks_support({"http": "http://127.0.0.1:8080"})
