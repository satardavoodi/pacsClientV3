"""OPT-33 guard — every outbound EchoMind AI call must carry a timeout.

Why this matters (2026-07-13 connectivity review):

`openai_reporter.py` issued all ten `requests.post(...)` calls to the external AI
endpoint with **no `timeout=`**, i.e. requests waits forever. That is NOT a crash
— each call runs on an `ApiWorker` QThread wrapped in try/except, so the app
survives and shows "check your internet connection". But on a **half-open**
connection (a link that dies mid-request — exactly what the field laptop's
network did, see OPT-28) the worker thread never returns:

  * the "typing…" bubble spins forever,
  * the Send button stays locked (`lock_btn`),
  * the QThread leaks — and every retry leaks another one.

That is the "EchoMind hangs / attenuates when the internet drops" symptom. A
clean refusal beats an infinite wait: with a timeout the worker raises, the
existing except path fires, and the user gets the "Connection error" bubble and
can retry.

Pure source/behaviour pins — no Qt, no network.
"""
import ast
import pathlib

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
_REPORTER = _REPO / "modules" / "EchoMind" / "viewer_chat" / "openai_reporter.py"
_MIRROR = (
    _REPO / "builder" / "plugin package" / "packages" / "echomind" / "payload"
    / "python" / "modules" / "EchoMind" / "viewer_chat" / "openai_reporter.py"
)


def _outbound_calls(src: str):
    """Every requests.<verb>(...) call node in the module."""
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (
            isinstance(fn, ast.Attribute)
            and isinstance(fn.value, ast.Name)
            and fn.value.id == "requests"
            and fn.attr in {"get", "post", "put", "patch", "delete", "head", "request"}
        ):
            out.append(node)
    return out


def test_every_outbound_ai_call_has_a_timeout():
    src = _REPORTER.read_text(encoding="utf-8")
    calls = _outbound_calls(src)
    assert calls, "expected outbound requests.* calls in openai_reporter"
    missing = [
        c.lineno for c in calls
        if not any(kw.arg == "timeout" for kw in c.keywords)
    ]
    assert not missing, (
        "requests.* call(s) WITHOUT timeout= at line(s) "
        f"{missing} — a half-open link would hang the AI worker thread forever"
    )


def test_timeout_helper_is_a_connect_read_pair_by_default(monkeypatch):
    import importlib

    mod = importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")
    monkeypatch.delenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", raising=False)
    t = mod._request_timeout()
    assert isinstance(t, tuple) and len(t) == 2, "must be a (connect, read) pair"
    connect, read = t
    assert 0 < connect <= 30, "a CONNECT must fail fast"
    assert read >= 60, "a long LLM completion needs a generous READ budget"


def test_kill_switch_restores_the_legacy_no_timeout(monkeypatch):
    import importlib

    mod = importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")
    monkeypatch.setenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", "0")
    assert mod._request_timeout() is None, (
        "=0 must restore the byte-identical legacy behaviour (wait forever)"
    )


def test_read_timeout_is_tunable(monkeypatch):
    import importlib

    mod = importlib.import_module("modules.EchoMind.viewer_chat.openai_reporter")
    monkeypatch.setenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", "45")
    assert mod._request_timeout()[1] == 45.0
    monkeypatch.setenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", "garbage")
    assert mod._request_timeout()[1] == mod._DEFAULT_READ_TIMEOUT_S  # never raises


@pytest.mark.skipif(not _MIRROR.exists(), reason="plugin mirror absent in this checkout")
def test_plugin_mirror_carries_the_fix():
    """openai_reporter.py IS plugin-mirrored — a stale payload would ship the
    hanging version to the installed build."""
    mirror_calls = _outbound_calls(_MIRROR.read_text(encoding="utf-8"))
    missing = [
        c.lineno for c in mirror_calls
        if not any(kw.arg == "timeout" for kw in c.keywords)
    ]
    assert not missing, "run tools/dev/sync_plugin_mirrors.py (on the Windows host)"
