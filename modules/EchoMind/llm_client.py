"""
EchoMind/llm_client.py
======================
Single gateway for ALL LLM (GapGPT) calls in AIPacs.

USAGE — from anywhere in the app:
    from modules.EchoMind.llm_client import gapgpt_chat

    reply = gapgpt_chat(
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user",   "content": user_text},
        ]
    )

How the key is resolved
-----------------------
The GapGPT Bearer token is resolved entirely from modules.EchoMind Settings:

  1. User enters their EchoMind credential in Settings → EchoMind → Authenticate
  2. APIKeyManager.validate_key() maps the credential to a CenterRecord
  3. Manage.detect_center() stores the active CenterRecord (contains gapgpt_key)
  4. gapgpt_chat() calls Manage.get_center_and_gapgpt_key() on every request

No API key ever needs to be passed by callers.  Callers only provide messages,
model, and optional tuning parameters.

Usage logging
-------------
Every successful call logs prompt_tokens + completion_tokens to the local
database via Manage.update_usage().  This drives the Usage table shown in
Settings → modules.EchoMind.

Exceptions
----------
LLMNoKeyError — EchoMind Settings has not been authenticated yet
LLMAuthError  — GapGPT returned 401 (key invalid / expired)
LLMAPIError   — Other HTTP error or malformed response

All three inherit from LLMError, so callers can catch just LLMError if they
do not need to distinguish the failure mode.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

# ── Connection settings — single source of truth is ai_chat_config.py ────────
from modules.EchoMind.ai_chat_config import GAPGPT_API_URL, GAPGPT_DEFAULT_MODEL, GAPGPT_TIMEOUT

_API_URL         = GAPGPT_API_URL
_DEFAULT_MODEL   = GAPGPT_DEFAULT_MODEL
_DEFAULT_TIMEOUT = GAPGPT_TIMEOUT


# ── Exceptions ────────────────────────────────────────────────────────────────

class LLMError(Exception):
    """Base class for all EchoMind LLM gateway errors."""


class LLMNoKeyError(LLMError):
    """
    EchoMind Settings has no validated center / GapGPT key yet.
    Ask the user to open Settings → EchoMind and authenticate.
    """


class LLMAuthError(LLMError):
    """GapGPT rejected the request (401 – key is invalid or expired)."""


class LLMAPIError(LLMError):
    """GapGPT returned a non-200 response or the response was malformed."""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _resolve_gapgpt_key() -> tuple[str, str]:
    """
    Return (center_display, gapgpt_key) from the active EchoMind session.

    Raises LLMNoKeyError if the user has not authenticated in EchoMind Settings.
    """
    try:
        from modules.EchoMind.api_manager import Manage
        center, key = Manage.instance().get_center_and_gapgpt_key()
        if not key or not key.strip():
            raise LLMNoKeyError(
                "No GapGPT key resolved. Open Settings → EchoMind and authenticate."
            )
        return center or "Unknown", key.strip()
    except LLMNoKeyError:
        raise
    except Exception as exc:
        raise LLMNoKeyError(
            f"Could not resolve GapGPT key from modules.EchoMind Settings: {exc}"
        ) from exc


def _log_usage(
    center: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    user_msg: str,
) -> None:
    """Log token usage to the local database (best-effort — never raises)."""
    try:
        from modules.EchoMind.api_manager import Manage
        Manage.instance().update_usage(
            center.strip() or "Unknown",
            model.strip() or _DEFAULT_MODEL,
            prompt_tokens,
            completion_tokens,
            user_msg,
        )
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────────

def gapgpt_chat(
    messages: list[dict[str, Any]],
    *,
    model: str = _DEFAULT_MODEL,
    max_tokens: int | None = None,
    temperature: float = 0.0,
    timeout: int = _DEFAULT_TIMEOUT,
) -> str:
    """
    Send a chat-completion request to GapGPT and return the reply text.

    Parameters
    ----------
    messages : list of {"role": ..., "content": ...}
        The conversation turns.  Include a system prompt as the first message.
    model : str
        GapGPT model name.  Defaults to "gpt-4.1-mini".
    max_tokens : int | None
        Optional ceiling on output tokens.
    temperature : float
        Sampling temperature (0 = fully deterministic).
    timeout : int
        HTTP request timeout in seconds (default 60).

    Returns
    -------
    str
        The assistant's reply text (stripped).

    Raises
    ------
    LLMNoKeyError
        If EchoMind Settings has not been authenticated yet.
    LLMAuthError
        If GapGPT returns 401 (key invalid / expired).
    LLMAPIError
        On other HTTP errors or a malformed response body.
    """
    center, api_key = _resolve_gapgpt_key()

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(_API_URL, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise LLMAPIError(f"Network error contacting GapGPT: {exc}") from exc

    if resp.status_code == 401:
        raise LLMAuthError(
            "GapGPT returned 401 – key is invalid or expired. "
            "Update your credential in Settings → modules.EchoMind."
        )

    if resp.status_code != 200:
        snippet = (resp.text or "")[:300].replace("\n", " ")
        raise LLMAPIError(f"GapGPT HTTP {resp.status_code}: {snippet}")

    try:
        body: dict[str, Any] = resp.json()
        content: str = str(body["choices"][0]["message"]["content"]).strip()
    except Exception as exc:
        raise LLMAPIError(f"Malformed GapGPT response: {exc}") from exc

    # Log usage (silently — never raises)
    usage = body.get("usage") or {}
    user_msg = next(
        (str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    _log_usage(
        center=center,
        model=model,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        user_msg=user_msg[:500],
    )

    log.debug(
        "gapgpt_chat ok | model=%s prompt_tokens=%s completion_tokens=%s",
        model,
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
    )
    return content
