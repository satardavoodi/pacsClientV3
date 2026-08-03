"""Guards for F7 / F10 / F11 / F12 — the hardening pass (2026-07-28).

F7  backend dispatch was written out at TWELVE call sites as
    `X if backend == "openai" else Y`. Each was correct, but a NEW feature that
    forgets the ternary silently ignores the user's LLM selection — and no test
    would catch it. `openai_reporter._openai_result` was an abandoned attempt at
    exactly this unification: fully implemented, never called.
F10 `Manage.update_usage` did an unlocked read-modify-write of api_usage.json on
    every response, on whatever ApiWorker thread got it → lost token counts.
F11 `load_settings()` re-parsed the JSON file ~6× per LLM request.
F12 no retry anywhere; and the SOCKS5 preflight ran only on the two Settings
    "Test Connection" helpers, never on the real chat path.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import threading

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")


def _pages_src() -> str:
    with open(_PAGES, encoding="utf-8") as fh:
        return fh.read()


# ── F7: one dispatch authority ──────────────────────────────────────────────

def test_the_authority_helpers_exist():
    src = _pages_src()
    assert "def _ai_backend()" in src
    assert "def _ai_module(" in src
    assert "def _ai_model(" in src


def test_no_call_site_picks_an_implementation_with_an_inline_ternary():
    """The DISPATCH pattern `X if backend == "openai" else Y` must be gone.

    Scope note: a plain `if backend == "openai":` BLOCK is fine and still
    present — e.g. `_refresh_api_prompt` uses one to decide which welcome text
    and enable-state to show. That is UI state, not a choice of AI
    implementation. The defect was the one-line ternary that selected the
    module/function/model to CALL, repeated at twelve sites.
    """
    src = _pages_src().splitlines()
    offenders = []
    for i, line in enumerate(src, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # the explanatory comment block
        if 'if backend == "openai" else' not in line:
            continue
        if 'return "openai" if' in line:
            continue  # the authority itself
        offenders.append(f"{i}: {stripped}")
    assert not offenders, (
        "these call sites still pick the implementation themselves — route them "
        "through _ai_module()/_ai_model():\n  " + "\n  ".join(offenders)
    )


def test_no_call_site_imports_the_company_module_dynamically():
    src = _pages_src()
    assert 'fromlist=["BreastExpertAssistant"]' not in src
    assert 'fromlist=["ImageQualityAnalyzer"]' not in src
    assert 'fromlist=["reporter"]' not in src
    assert 'fromlist=["chat"]' not in src


def test_both_backend_modules_expose_the_same_feature_surface():
    """`_ai_module()` returns either module — they must be interchangeable."""
    company = importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")
    openai_side = importlib.import_module("modules.EchoMind.viewer_chat.openai_parallel_backend")
    for fn in (
        "reporter", "correction", "standardize", "standard_assist_search",
        "translate_text_to_persian", "translate_report",
        "BreastExpertAssistant", "ImageQualityAnalyzer", "chat",
    ):
        assert callable(getattr(company, fn, None)), f"openai_reporter.{fn} missing"
        assert callable(getattr(openai_side, fn, None)), f"openai_parallel_backend.{fn} missing"


def test_the_dead_unification_helper_is_gone():
    company = importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")
    assert not hasattr(company, "_openai_result"), (
        "dead code: it was never called and invited confusion with the real path"
    )


def test_the_unreachable_hardcoded_gapgpt_post_is_gone():
    path = os.path.join(_ROOT, "modules", "EchoMind", "secretary", "parser_llm.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    assert 'requests.post("https://api.gapgpt.app' not in src, (
        "that block sat AFTER a return and referenced an un-imported `requests` "
        "— a NameError waiting for whoever removed the early return"
    )


# ── F10: the usage write is locked ──────────────────────────────────────────

def test_usage_updates_are_serialised():
    api_manager = importlib.import_module("modules.EchoMind.api_manager")
    assert hasattr(api_manager, "_USAGE_LOCK")
    assert isinstance(api_manager._USAGE_LOCK, type(threading.Lock()))
    with open(api_manager.__file__, encoding="utf-8") as fh:
        src = fh.read()
    assert src.count("with _USAGE_LOCK:") == 2, (
        "both update_usage and update_usage_total must hold the lock across "
        "their read-modify-write"
    )


def test_concurrent_usage_updates_do_not_lose_counts(tmp_path, monkeypatch):
    """Behavioural: 8 threads x 25 increments must total 200, not fewer."""
    api_manager = importlib.import_module("modules.EchoMind.api_manager")
    usage_file = tmp_path / "api_usage.json"

    mgr = api_manager.Manage.instance()
    monkeypatch.setattr(mgr, "_get_usage_file", lambda: usage_file)
    monkeypatch.setattr(mgr, "is_validated", lambda: True)
    info = api_manager.CenterInfo(
        center_code="TEST", center_display="Test", irannobat_key="k", gapgpt_key="g"
    )
    monkeypatch.setattr(mgr, "ensure_detected", lambda: info)
    monkeypatch.setattr(mgr, "get_irannobat_key", lambda: "k")
    # The SQLite mirror is irrelevant here and unavailable in a unit test.
    monkeypatch.setitem(os.environ, "AIPACS_TEST_USAGE", "1")

    def _hammer():
        for _ in range(25):
            mgr.update_usage("m", 1, 1)

    threads = [threading.Thread(target=_hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads(usage_file.read_text(encoding="utf-8"))
    node = next(iter(data["keys"].values()))["models"]["m"]
    assert node["requests"] == 200, f"lost updates: {node['requests']}/200"
    assert node["total_tokens"] == 400


# ── F11: settings cache is identity-keyed, not time-keyed ───────────────────

@pytest.fixture
def store(tmp_path, monkeypatch):
    ss = importlib.import_module("modules.EchoMind.settings_store")
    monkeypatch.setattr(ss, "_config_path", lambda: tmp_path / "echomind_settings.json")
    ss._invalidate_settings_cache()
    return ss


def test_repeated_loads_do_not_re_read_the_file(store, monkeypatch):
    store.save_settings({"api_key": "abc"})
    reads = {"n": 0}
    real_open = open

    def _counting_open(*a, **kw):
        if a and str(a[0]).endswith("echomind_settings.json"):
            reads["n"] += 1
        return real_open(*a, **kw)

    monkeypatch.setattr("builtins.open", _counting_open)
    for _ in range(6):
        store.load_settings()
    # 1, not 6: `save_settings` deliberately invalidates, so the first load after
    # a write re-reads; the other five are served from the identity-keyed cache.
    # Before F11 this was 6 — and a single LLM request performs ~6 loads.
    assert reads["n"] == 1, f"cache not effective: {reads['n']} re-reads for 6 loads"


def test_a_save_is_visible_immediately(store):
    """The per-call resolution contract: no restart, no TTL wait."""
    store.save_settings({"stt_provider": "aipacs_1"})
    assert store.get_stt_provider() == "aipacs_1"
    store.save_settings({"stt_provider": "aipacs_2"})
    assert store.get_stt_provider() == "aipacs_2", "stale cache served after a save"


def test_an_external_edit_is_picked_up(store, tmp_path):
    store.save_settings({"api_key": "one"})
    assert store.get_echomind_api_key() == "one"
    # Simulate another process rewriting the file.
    fp = tmp_path / "echomind_settings.json"
    data = json.loads(fp.read_text(encoding="utf-8"))
    data["api_key"] = "two"
    fp.write_text(json.dumps(data), encoding="utf-8")
    assert store.get_echomind_api_key() == "two", (
        "cache is keyed on (mtime_ns, size) — an external write must invalidate it"
    )


def test_a_mutated_result_cannot_poison_the_cache(store):
    store.save_settings({"api_key": "x"})
    first = store.load_settings()
    first["api_key"] = "TAMPERED"
    assert store.load_settings()["api_key"] == "x"


def test_corrupt_file_falls_back_to_defaults_and_is_not_cached(store, tmp_path):
    (tmp_path / "echomind_settings.json").write_text("{not json", encoding="utf-8")
    out = store.load_settings()
    assert out["llm_backend"] == "company"  # defaults
    assert store._cache_value is None, "a failed parse must not be cached"


# ── F12: one retry, only when provably safe ─────────────────────────────────

@pytest.fixture(scope="module")
def H():
    return importlib.import_module("modules.EchoMind.echomind_http")


def test_a_connect_failure_is_retried_once(H, monkeypatch):
    import requests as rq
    calls = {"n": 0}

    def _flaky(url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise rq.exceptions.ConnectionError(
                "HTTPSConnectionPool: Failed to establish a new connection"
            )
        return "OK"

    monkeypatch.delenv("AIPACS_ECHOMIND_HTTP_RETRY", raising=False)
    monkeypatch.setattr(H.requests, "post", _flaky)
    assert H.post("http://x/y", json={}) == "OK"
    assert calls["n"] == 2


def test_a_read_timeout_is_NEVER_retried(H, monkeypatch):
    """The server may already have processed it — a retry would duplicate work."""
    import requests as rq
    calls = {"n": 0}

    def _slow(url, **kw):
        calls["n"] += 1
        raise rq.exceptions.ReadTimeout("read timed out")

    monkeypatch.setattr(H.requests, "post", _slow)
    with pytest.raises(rq.exceptions.ReadTimeout):
        H.post("http://x/y", json={})
    assert calls["n"] == 1, "a read timeout must not be re-sent"


def test_a_mid_stream_reset_is_not_retried(H, monkeypatch):
    """A bare ConnectionError can mean 'reset after the server did the work'."""
    import requests as rq
    calls = {"n": 0}

    def _reset(url, **kw):
        calls["n"] += 1
        raise rq.exceptions.ConnectionError("Connection aborted, RemoteDisconnected")

    monkeypatch.setattr(H.requests, "post", _reset)
    with pytest.raises(rq.exceptions.ConnectionError):
        H.post("http://x/y", json={})
    assert calls["n"] == 1


def test_a_file_upload_is_never_retried(H, monkeypatch):
    """The file object is consumed by the first attempt — a retry truncates it."""
    import requests as rq
    calls = {"n": 0}

    def _flaky(url, **kw):
        calls["n"] += 1
        raise rq.exceptions.ConnectTimeout("connect timed out")

    monkeypatch.setattr(H.requests, "post", _flaky)
    with pytest.raises(rq.exceptions.ConnectTimeout):
        H.post("http://x/y", files={"file": ("a.wav", b"x")})
    assert calls["n"] == 1


def test_an_http_error_status_is_not_retried(H, monkeypatch):
    calls = {"n": 0}

    class _Resp:
        status_code = 500

    def _err(url, **kw):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(H.requests, "post", _err)
    assert H.post("http://x/y", json={}).status_code == 500
    assert calls["n"] == 1, "a server answer is not a transport failure"


def test_retry_kill_switch(H, monkeypatch):
    import requests as rq
    calls = {"n": 0}

    def _flaky(url, **kw):
        calls["n"] += 1
        raise rq.exceptions.ConnectTimeout("connect timed out")

    monkeypatch.setenv("AIPACS_ECHOMIND_HTTP_RETRY", "0")
    monkeypatch.setattr(H.requests, "post", _flaky)
    with pytest.raises(rq.exceptions.ConnectTimeout):
        H.post("http://x/y", json={})
    assert calls["n"] == 1


def test_socks_preflight_now_runs_on_the_real_chat_path():
    """It used to guard only the two Settings 'Test Connection' helpers."""
    path = os.path.join(_ROOT, "modules", "EchoMind", "llm_client.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    body = src.split("def chat_completion(", 1)[1].split("\ndef ", 1)[0]
    assert "_ensure_socks_proxy_support(" in body, (
        "with SOCKS5 selected and PySocks missing, the real chat surfaced a "
        "generic transport error instead of the actionable install message"
    )
