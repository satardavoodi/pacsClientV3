"""LLM connection settings for the Reception CRM agent.

Mirrors the workstation's ``modules/EchoMind/ai_chat_config.py`` transport
constants, but every credential comes from the **environment** — never from a
config file in the repo, and never from a client (the phone authenticates to
the gateway; the gateway authenticates to the LLM).

Environment variables
---------------------
RECEPTION_LLM_BACKEND          "company" (Iran Nobat, default) | "openai"
RECEPTION_LLM_API_KEY          company backend: overrides the key shipped in
                               the build (see ``company_backend.py``)
RECEPTION_LLM_MODEL            model override (default: GAPGPT_DEFAULT_MODEL)
RECEPTION_LLM_TIMEOUT          seconds (default: 60)
RECEPTION_LLM_TEMPERATURE      float (default: 0.0 — deterministic tool selection)
RECEPTION_LLM_MAX_TOKENS       int (default: 1200)
RECEPTION_LLM_PROXY            "" (direct, default) | "socks5://127.0.0.1:2080"
RECEPTION_OPENAI_API_KEY       openai backend key
RECEPTION_OPENAI_BASE_URL      default https://api.openai.com/v1
RECEPTION_OPENAI_ORG           optional
RECEPTION_OPENAI_PROJECT       optional
"""

from __future__ import annotations

import os

from . import company_backend

# --- Iran Nobat transport constants -----------------------------------------
# The values now live in ``company_backend`` so there is exactly one place that
# describes the default backend. These aliases stay because the client and the
# tests import them by these names.
GAPGPT_API_URL = company_backend.API_URL
GAPGPT_DEFAULT_MODEL = company_backend.MODEL
GAPGPT_TIMEOUT = company_backend.TIMEOUT

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"

# Deterministic tool selection: the interpreter is a classifier, not a writer.
DEFAULT_TEMPERATURE = company_backend.TEMPERATURE
DEFAULT_MAX_TOKENS = company_backend.MAX_TOKENS


def backend() -> str:
    return "openai" if _env("RECEPTION_LLM_BACKEND", "company").lower() == "openai" else "company"


def company_api_key(stored: str = "") -> str:
    """The Iran Nobat key: environment, then the key shipped in this build.

    ``stored`` lets a caller pass a technician-entered key as a last resort; the
    normal install has nothing stored and relies on the bundled value.
    """
    return company_backend.api_key(stored)


def openai_settings() -> dict[str, str]:
    return {
        "api_key": _env("RECEPTION_OPENAI_API_KEY", ""),
        "base_url": _env("RECEPTION_OPENAI_BASE_URL", OPENAI_DEFAULT_BASE_URL) or OPENAI_DEFAULT_BASE_URL,
        "organization": _env("RECEPTION_OPENAI_ORG", ""),
        "project": _env("RECEPTION_OPENAI_PROJECT", ""),
    }


def model() -> str:
    """The model to call.

    The company backend ships a model chosen and measured at build time, so a
    clinic has nothing to pick and a stale settings file cannot name a retired
    model. That default stands.

    What changed: it is now a DEFAULT rather than a prohibition. The previous
    version returned ``company_backend.MODEL`` unconditionally and ignored the
    environment entirely -- which meant the ``llm.model`` field that the
    installer asks the operator to fill in, that ``server.json`` stores, and
    that ``describe`` prints back, did nothing at all on the default backend.
    It read "gpt-5.2" and the build used "gpt-5.2", so the two agreed by
    coincidence and nobody could see that one was not driving the other. The
    day they diverged, `describe` would have confidently reported a model the
    server was not calling.

    So: an explicit override wins, and `describe` reports what this function
    returns rather than what the module constant says. That also makes a model
    swap or a rollback a config edit and a restart, instead of a rebuild and a
    redeploy onto a clinical machine.
    """
    override = _env("RECEPTION_LLM_MODEL", "")
    if override:
        return override
    if backend() == "company":
        return company_backend.MODEL
    return GAPGPT_DEFAULT_MODEL


def timeout() -> int:
    return _int("RECEPTION_LLM_TIMEOUT", company_backend.TIMEOUT)


def temperature() -> float:
    try:
        return float(_env("RECEPTION_LLM_TEMPERATURE", str(DEFAULT_TEMPERATURE)))
    except ValueError:
        return DEFAULT_TEMPERATURE


def max_tokens() -> int:
    return _int("RECEPTION_LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS)


def proxies() -> dict[str, str]:
    """requests-compatible proxies dict.

    Empty dict = explicit bypass of *all* proxy sources (system registry,
    HTTP(S)_PROXY env vars). Passing ``None`` would let requests pick up system
    proxies — the workstation makes the same distinction deliberately.
    """
    url = _env("RECEPTION_LLM_PROXY", "")
    if not url:
        return {}
    return {"http": url, "https": url}


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default
