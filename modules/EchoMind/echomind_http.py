"""The ONE place EchoMind decides HOW an outbound HTTP call is routed.

WHY THIS MODULE EXISTS (F3 + F6, 2026-07-28)
--------------------------------------------
EchoMind made the same two transport decisions — *which proxy* and *what
timeout* — independently at 19 call sites, and got different answers.

**Proxy.** `llm_client.py` and `openai_reporter.py` each carried their own copy
of `_get_requests_proxies()` and passed `proxies=` on every request. The four
main chat modes (`URL_CHAT`, `URL_GEN_REPORT`, `URL_GEN_ASSISTANT`,
`URL_SEARCH`), every voice-to-text upload, and the OpenAI STT provider passed
nothing at all. Meanwhile Settings ▸ EchoMind tells the user:

    "When SOCKS5 is selected, all EchoMind API calls are tunnelled through the
     local proxy at 127.0.0.1."

That was false for roughly half the module, and the *`direct`* case was the
worse half: `requests` defaults to ``trust_env=True``, so the un-proxied calls
still picked up the Windows registry proxy and ``HTTP(S)_PROXY`` — i.e.
selecting "direct" did **not** bypass a system proxy for them. On a restricted
hospital network that produces the classic "the AI works but voice doesn't"
(or the reverse) report.

**Timeout.** OPT-33 established `(connect=10, read=180)` for EchoMind AI calls,
but only `openai_reporter.py` ever used it. `llm_client.chat_completion` used a
scalar 60 s, the chat modes a scalar 300 s, voice a scalar 360 s. A scalar
applies to the *connect* phase too, so an unreachable host took 60–360 s to
report itself instead of 10 s — and the SAME report-generation feature got a
180 s read budget on the company backend but only 60 s on OpenAI.

THE RULE
--------
Every EchoMind outbound call goes through `post()` / `get()` here, or at minimum
takes its `proxies=` from `requests_proxies()` and its `timeout=` from
`resolve_timeout()`. Do not re-derive either at a call site, and do not add a
third copy of the proxy dict. A guard test
(`tests/code/echomind/test_echomind_http_authority.py`) fails the suite if a
bare `requests.post(`/`requests.get(` appears in the EchoMind AI/voice paths.

SCOPE — deliberately NOT everything in the package
--------------------------------------------------
The reception/RIS calls in `ai_chat_pages._send_with_patient_id` are **excluded
on purpose**. They target the hospital's own reception server, not an EchoMind
AI endpoint; forcing them through a SOCKS5 tunnel provisioned for AI access
would break a working local integration. Reception has its own configuration
(`modules/network/reception_api_config.py`) and should grow its own policy if
one is ever needed.

KILL SWITCHES
-------------
* ``AIPACS_ECHOMIND_PROXY_AUTHORITY=0`` — `requests_proxies()` returns ``None``,
  i.e. every call reverts to the pre-fix "let requests decide" behaviour.
* ``AIPACS_ECHOMIND_HTTP_TIMEOUT=0``    — no timeout at all (legacy hang; the
  pre-existing OPT-33 switch, honoured here unchanged).
* ``AIPACS_ECHOMIND_HTTP_TIMEOUT=<n>``  — override the READ timeout in seconds.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional, Tuple, Union

import requests

from .settings_store import get_proxy_settings

log = logging.getLogger(__name__)

_ENV_PROXY_AUTHORITY = "AIPACS_ECHOMIND_PROXY_AUTHORITY"
_ENV_TIMEOUT = "AIPACS_ECHOMIND_HTTP_TIMEOUT"

# (connect, read). A connect must fail fast; a long LLM completion legitimately
# needs a generous read budget. Both are the OPT-33 values, now applied module-
# wide instead of in openai_reporter.py only.
DEFAULT_CONNECT_TIMEOUT_S = 10.0
DEFAULT_READ_TIMEOUT_S = 180.0

#: Uploading a voice file and waiting for a server-side Whisper pass is a
#: legitimately long operation — far longer than a chat completion. Callers that
#: need it pass `read=` explicitly; this constant documents the intent.
UPLOAD_READ_TIMEOUT_S = 360.0

TimeoutT = Union[None, float, Tuple[float, float]]


# ── proxy ────────────────────────────────────────────────────────────────────

def proxy_authority_enabled() -> bool:
    """Kill switch. ``0`` = never pass ``proxies=`` (pre-fix behaviour)."""
    raw = os.environ.get(_ENV_PROXY_AUTHORITY)
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def requests_proxies() -> Optional[Dict[str, str]]:
    """The proxies dict for EVERY EchoMind call. Never raises.

    * ``direct`` → ``{}``. This is NOT the same as ``None``: an empty dict makes
      ``requests`` bypass ALL proxy sources (Windows registry / WinInet,
      ``HTTP_PROXY`` / ``HTTPS_PROXY``). Passing ``None`` would let them apply,
      which is exactly the bug this module fixes.
    * ``socks5``  → the configured local SOCKS5 proxy.
    * flag off / any failure → ``None`` (legacy "let requests decide").
    """
    if not proxy_authority_enabled():
        return None
    try:
        cfg = get_proxy_settings()
        if cfg.get("connection_type") != "socks5":
            return {}  # explicit bypass — no system/env proxy
        port = int(cfg.get("proxy_port") or 2080)
        proxy_url = f"socks5://127.0.0.1:{port}"
        return {"http": proxy_url, "https": proxy_url}
    except Exception:
        return {}  # fail-safe: no proxy, still an explicit bypass


def socks5_selected() -> bool:
    """True when Settings asks for the SOCKS5 tunnel."""
    try:
        return get_proxy_settings().get("connection_type") == "socks5"
    except Exception:
        return False


def ensure_socks_support(proxies: Optional[Dict[str, str]]) -> None:
    """Raise a *useful* error when SOCKS5 is selected but PySocks is missing.

    Previously this check existed only on the two Settings "Test Connection"
    paths, so a real chat request with SOCKS5 configured and no PySocks surfaced
    a generic transport error instead of the actionable one.
    """
    if not proxies:
        return
    if not any("socks" in str(v).lower() for v in proxies.values()):
        return
    try:
        import socks  # type: ignore  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "SOCKS5 proxy is selected in Settings ▸ EchoMind, but SOCKS support "
            "is not available in this Python environment. Install "
            "requests[socks] / PySocks, or switch the connection type back to "
            "Direct."
        ) from exc


# ── timeout ──────────────────────────────────────────────────────────────────

def resolve_timeout(timeout: TimeoutT = None, *, read: Optional[float] = None) -> TimeoutT:
    """The ``timeout=`` for an EchoMind call.

    * an explicit ``timeout`` from the caller wins for the READ budget -- it is
      the user's configured Settings value, and an admin who lowers it to fail
      fast must get what they asked for. It is still upgraded to a tuple so the
      CONNECT phase keeps its own ceiling;
    * ``read=`` supplies the read budget only when the caller passed no
      ``timeout`` at all;
    * ``AIPACS_ECHOMIND_HTTP_TIMEOUT=<n>`` overrides the read budget in BOTH
      cases -- it is the support escape hatch, and until 2026-07-31 it was
      silently dead for every call that also passed an explicit ``timeout=``;
    * ``AIPACS_ECHOMIND_HTTP_TIMEOUT=0`` → ``None`` = wait forever (legacy);
    * otherwise ``(connect, read)``.

    A SCALAR is deliberately never returned by default: a scalar applies to the
    connect phase too, which is what made an unreachable host take minutes to
    report itself.
    """
    raw = (os.getenv(_ENV_TIMEOUT, "") or "").strip()
    if raw == "0":
        return None  # kill switch: byte-identical legacy (wait forever)

    if timeout is not None:
        # Honour an explicit caller value, but upgrade a bare scalar into
        # (connect, read) so it still fails fast on connect.
        #
        # 2026-07-31 -- this branch used to return BEFORE `read=` was ever
        # consulted. All three voice-upload call sites pass BOTH
        # `timeout=<stt_timeout_seconds>` and
        # `read_timeout=UPLOAD_READ_TIMEOUT_S`, so the 360 s upload budget --
        # the entire reason that constant exists -- was silently dropped, and
        # the documented `AIPACS_ECHOMIND_HTTP_TIMEOUT=<n>` override had no
        # effect on voice or on the Settings probes either. A caller asking for
        # a LONGER read budget must get it. The connect ceiling is unchanged.
        if isinstance(timeout, (int, float)):
            connect_s = min(float(DEFAULT_CONNECT_TIMEOUT_S), float(timeout))
            read_s = float(timeout)
            # `read=` deliberately does NOT raise this. An explicit caller
            # timeout is the user's Settings value (Voice to Text -> Timeout,
            # whose own default is already UPLOAD_READ_TIMEOUT_S), and an admin
            # who lowers it to fail fast must get what they asked for.
            if raw:
                try:
                    read_s = float(raw)
                except ValueError:
                    pass
            return (connect_s, read_s)
        return timeout

    read_s = float(read if read is not None else DEFAULT_READ_TIMEOUT_S)
    if raw:
        try:
            read_s = float(raw)
        except ValueError:
            pass
    return (DEFAULT_CONNECT_TIMEOUT_S, read_s)


# ── the wrappers every EchoMind call should use ──────────────────────────────

def _with_transport(kwargs: Dict[str, Any], *, read: Optional[float] = None) -> Dict[str, Any]:
    if "proxies" not in kwargs:
        proxies = requests_proxies()
        if proxies is not None:
            kwargs["proxies"] = proxies
    kwargs["timeout"] = resolve_timeout(kwargs.get("timeout"), read=read)
    return kwargs


# ── F12: exactly one automatic retry, and ONLY when it is provably safe ──────
# EchoMind had no retry anywhere: a single dropped TCP handshake surfaced as
# "check your internet" and the physician had to click Retry. On the flaky links
# at the field sites that is most of the user-visible failures.
#
# THE SAFETY RULE — retry ONLY on a CONNECT-phase failure. A `ConnectTimeout` or
# `ConnectionError` means the request never reached the server, so re-sending it
# cannot duplicate work. A **ReadTimeout is NOT retried**: the server may have
# already accepted and processed the request, and silently re-submitting a
# report generation (or a reception write) would be a duplicate clinical action.
# An HTTP error status is never retried either — that is the server answering.
#
# Requests carrying `files=` are also excluded: the file object has already been
# consumed by the first attempt, so a retry would upload a truncated body.
_ENV_RETRY = "AIPACS_ECHOMIND_HTTP_RETRY"

#: Markers that identify a failure during the CONNECT phase specifically.
#: A bare `ConnectionError` is NOT enough — urllib3 also raises it for a reset
#: mid-response, which happens AFTER the server may have processed the request.
_CONNECT_PHASE_MARKERS = (
    "failed to establish a new connection",
    "newconnectionerror",
    "nameresolutionerror",
    "getaddrinfo failed",
    "temporary failure in name resolution",
    "connection refused",
    "actively refused",
    "winerror 10061",
    "no route to host",
    "network is unreachable",
)


def connect_retry_enabled() -> bool:
    """Kill switch for the single connect-phase retry (default ON)."""
    raw = os.environ.get(_ENV_RETRY)
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def is_connect_phase_failure(exc: BaseException) -> bool:
    """True only when the request provably never reached the server.

    `ConnectTimeout` is unambiguous. A plain `ConnectionError` is not — it also
    covers a reset partway through a response, and re-sending THAT could
    duplicate work the server already did. So we require a connect-phase marker
    in the message before treating it as safe to retry.
    """
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return False
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return True
    if isinstance(exc, requests.exceptions.ConnectionError):
        text = f"{exc}".lower()
        return any(marker in text for marker in _CONNECT_PHASE_MARKERS)
    return False


# ── connection reuse: DEFERRED, deliberately (2026-07-31) ────────────────────
# Every call goes through the module-level `requests.post` / `requests.get`,
# and each of those builds a THROWAWAY Session — so every request pays a fresh
# TCP + TLS handshake. There is no `requests.Session` / `HTTPAdapter` anywhere
# in the EchoMind tree, all traffic concentrates on ~3 hosts, and one Secretary
# voice command can be four requests to the same host inside one user action:
# through a SOCKS5 tunnel at 250 ms RTT that is ~3 s of pure handshake.
#
# A thread-local `requests.Session` was implemented and then REVERTED, because
# it moves the call from `requests.post` to `Session.post` — and that is the
# exact seam three test files monkeypatch to intercept EchoMind's traffic
# (`test_echomind_http_authority`, `test_backend_authority_and_hardening`,
# `test_voice_transcription_service`). With the session in place those patches
# stopped intercepting and the tests dialled the real network.
#
# Landing it properly means re-pointing those tests at `echomind_http._session`
# and giving them a fake session object. That is a real test refactor, not a
# one-liner, and it must not be done blind — the alternative considered and
# rejected was an autouse fixture forcing keep-alive OFF in tests, which would
# leave the suite validating a path users never run.
#
# DO NOT reintroduce a Session here without doing that test work first.


def _endpoint(url: str) -> str:
    """`host/path` — no query string, no credentials. Safe for a shared log."""
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        return "%s%s" % (parts.hostname or "?", parts.path or "")
    except Exception:
        return "?"


def _send(verb, url: str, kwargs: Dict[str, Any]) -> "requests.Response":
    """Issue the request, and RECORD IT.

    2026-07-31 — until now `echomind_http` logged only on retry: no request
    start, no status, no elapsed time, no response size. Combined with
    `modules.EchoMind.viewer_chat.*` never logging at all, that made a simple
    question — "why was that report slow, and was it the server or us?" —
    unanswerable from the app log. It also meant a report could be written to
    the database with no trace of the request that produced it.

    What is logged: endpoint (host + path, never the query string), status,
    and the CONNECT/READ split, because a slow LLM and a slow SOCKS5 tunnel are
    indistinguishable without it. Never the body, never a header — same rule as
    F8: sizes and timings, not clinical content.
    """
    endpoint = _endpoint(url)
    timeout = kwargs.get("timeout")
    t0 = time.perf_counter()

    def _done(resp, retried: bool) -> "requests.Response":
        elapsed = int((time.perf_counter() - t0) * 1000)
        size = -1
        try:
            size = int((resp.headers or {}).get("Content-Length", -1))
        except Exception:
            size = -1
        log.info(
            "[EchoMind-HTTP] %s status=%s elapsed_ms=%d bytes=%s timeout=%s retried=%s",
            endpoint, getattr(resp, "status_code", "?"), elapsed, size, timeout, retried,
        )
        return resp

    try:
        return _done(verb(url, **kwargs), False)
    except requests.exceptions.RequestException as exc:
        elapsed = int((time.perf_counter() - t0) * 1000)
        phase = "connect" if is_connect_phase_failure(exc) else "read/other"
        log.warning(
            "[EchoMind-HTTP] %s FAILED phase=%s after_ms=%d timeout=%s err=%s",
            endpoint, phase, elapsed, timeout, type(exc).__name__,
        )
        if not connect_retry_enabled():
            raise
        if "files" in kwargs:
            raise  # the file object is already consumed — a retry would truncate
        if not is_connect_phase_failure(exc):
            raise
        log.info("[EchoMind-HTTP] connect failed (%s) — one retry", type(exc).__name__)
        return _done(verb(url, **kwargs), True)


def post(url: str, *, read_timeout: Optional[float] = None, **kwargs: Any) -> "requests.Response":
    """``requests.post`` with EchoMind's proxy + timeout + retry policy."""
    return _send(requests.post, url, _with_transport(kwargs, read=read_timeout))


def get(url: str, *, read_timeout: Optional[float] = None, **kwargs: Any) -> "requests.Response":
    """``requests.get`` with EchoMind's proxy + timeout + retry policy."""
    return _send(requests.get, url, _with_transport(kwargs, read=read_timeout))


__all__ = [
    "DEFAULT_CONNECT_TIMEOUT_S",
    "DEFAULT_READ_TIMEOUT_S",
    "UPLOAD_READ_TIMEOUT_S",
    "ensure_socks_support",
    "get",
    "post",
    "proxy_authority_enabled",
    "requests_proxies",
    "resolve_timeout",
    "socks5_selected",
]
