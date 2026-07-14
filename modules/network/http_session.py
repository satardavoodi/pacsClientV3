# -*- coding: utf-8 -*-
"""Shared, pooled HTTP sessions for the Reception / PACS REST channels.

WHY (2026-07-14)
----------------
Every REST call on the patient-list path used a bare ``requests.get(...)``, which
opens a **new TCP connection per call** and throws it away. The main page issues
one call per visible reception (reporting physician + report status) *and* one per
reception for the internal assignment, so a 24-row list paid 48 handshakes.

Measured against this center (24 receptions, PACS :8000):

    sequential + new connection each call ....... 1629 ms   (what we shipped)
    8 threads + keep-alive ......................  232 ms   (7.0x faster)

This module supplies ONE pooled, keep-alive session per base URL. It is the only
place HTTP connection policy lives, so every REST caller on the list path benefits
and none of them can regress it independently.

Thread-safety: a ``requests.Session`` is safe for concurrent GETs as long as the
connection pool is at least as large as the worker count — which is exactly what
``get_session`` sizes it to. Never raises.
"""
from __future__ import annotations

import os
import threading
from typing import Dict, Optional

try:
    import requests
    from requests.adapters import HTTPAdapter
except Exception:  # pragma: no cover - requests is a hard dep in practice
    requests = None  # type: ignore
    HTTPAdapter = object  # type: ignore

#: How many receptions we fetch in parallel on the patient-list path.
DEFAULT_WORKERS = 8
#: Ceiling — beyond this we would just queue on the server.
MAX_WORKERS = 16

_SESSIONS: Dict[str, "requests.Session"] = {}
_LOCK = threading.Lock()


def parallel_workers(default: int = DEFAULT_WORKERS) -> int:
    """Worker count for list-path REST fan-out (``AIPACS_RECEPTION_WORKERS``).

    ``1`` restores the old strictly-sequential behaviour.
    """
    try:
        n = int(os.environ.get("AIPACS_RECEPTION_WORKERS", "") or default)
    except Exception:
        n = default
    return max(1, min(MAX_WORKERS, n))


def keepalive_enabled() -> bool:
    """``AIPACS_HTTP_KEEPALIVE=0`` → a fresh connection per call (legacy)."""
    return (os.environ.get("AIPACS_HTTP_KEEPALIVE", "1") or "1").strip() != "0"


def get_session(base_url: str = "") -> Optional["requests.Session"]:
    """A pooled keep-alive session for *base_url* (or None to use bare requests).

    Sessions are cached per base URL so switching center (Razi ⇄ Mehr) keeps
    independent connection pools and a dead host's sockets are never reused for a
    healthy one.
    """
    if requests is None or not keepalive_enabled():
        return None
    key = str(base_url or "").strip().rstrip("/") or "_default"
    with _LOCK:
        sess = _SESSIONS.get(key)
        if sess is not None:
            return sess
        try:
            sess = requests.Session()
            pool = max(parallel_workers(), DEFAULT_WORKERS)
            adapter = HTTPAdapter(
                pool_connections=pool,
                pool_maxsize=pool,
                max_retries=0,      # the reception circuit breaker owns retry policy
            )
            sess.mount("http://", adapter)
            sess.mount("https://", adapter)
            _SESSIONS[key] = sess
            return sess
        except Exception:  # pragma: no cover - defensive
            return None


def http_get(url: str, *, base_url: str = "", **kwargs):
    """GET over the pooled session when possible, else a plain request."""
    sess = get_session(base_url)
    if sess is not None:
        return sess.get(url, **kwargs)
    return requests.get(url, **kwargs)


def http_put(url: str, *, base_url: str = "", **kwargs):
    sess = get_session(base_url)
    if sess is not None:
        return sess.put(url, **kwargs)
    return requests.put(url, **kwargs)


def reset_sessions() -> None:
    """Close every pooled session (center switch / logout / tests)."""
    with _LOCK:
        for sess in _SESSIONS.values():
            try:
                sess.close()
            except Exception:
                pass
        _SESSIONS.clear()
