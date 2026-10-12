"""Provider-aware LLM gateway for the Reception CRM agent.

Port of the AI-PACS workstation ``modules/EchoMind/llm_client.py``: same two
backends (company/GapGPT and OpenAI), same request shape, same error taxonomy,
same "explicit proxy bypass" behaviour, same truncation handling.

Differences from the workstation original (deliberate):
  * credentials come from the environment (``llm/config.py``), not from a Qt
    settings store or a key compiled into a client binary;
  * no ``api_manager`` center-key registry — the server holds the resolved key;
  * token usage is returned to the caller (the orchestrator audits it) instead
    of being written into the workstation's usage database.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import requests

from . import company_backend, config

log = logging.getLogger(__name__)

_SENTENCE_ENDINGS = ".!?。؟！？"


class LLMError(Exception):
    """Base class for all Reception CRM LLM gateway errors."""

    code = "LLM_ERROR"


class LLMNoKeyError(LLMError):
    """No usable backend key is configured for the selected provider."""

    code = "LLM_NO_KEY"


class LLMAuthError(LLMError):
    """The provider rejected the request with an authentication error."""

    code = "LLM_AUTH"


class LLMAPIError(LLMError):
    """The provider returned a non-success response or malformed data."""

    code = "LLM_API"


@dataclass(frozen=True)
class BackendSession:
    provider: str
    display_name: str
    api_key: str
    api_url: str
    organization: str = ""
    project: str = ""


def is_configured() -> bool:
    """Can a request actually be made right now?

    The company backend is configured by the build, so on a normal install this
    is true before the user has touched anything — which is the behaviour the
    settings screen reports as «آماده».
    """
    if os.environ.get("CRM_EAGLE_CONFIG"):
        return True
    if config.backend() == "openai":
        return bool(config.openai_settings()["api_key"])
    return bool(config.company_api_key())


def _resolve_company_backend() -> BackendSession:
    key = config.company_api_key()
    if not key:
        # A build that reached a clinic without its key is a packaging fault, not
        # something the user can fix, so the message says so rather than asking
        # them for a key they were never meant to have.
        raise LLMNoKeyError(
            "This build has no Iran Nobat key. It was packaged without "
            "reception_crm/llm/company_key.txt — rebuild with the key, or set "
            "RECEPTION_LLM_API_KEY on this machine."
        )
    return BackendSession(
        provider="company",
        display_name=company_backend.DISPLAY_NAME,
        api_key=key,
        api_url=company_backend.API_URL,
    )


def _resolve_openai_backend() -> BackendSession:
    cfg = config.openai_settings()
    if not cfg["api_key"]:
        raise LLMNoKeyError("No OpenAI API key is configured. Set RECEPTION_OPENAI_API_KEY.")
    base_url = (cfg["base_url"] or config.OPENAI_DEFAULT_BASE_URL).rstrip("/")
    return BackendSession(
        provider="openai",
        display_name="OpenAI",
        api_key=cfg["api_key"],
        api_url=f"{base_url}/chat/completions",
        organization=cfg["organization"],
        project=cfg["project"],
    )


def resolve_backend() -> BackendSession:
    if config.backend() == "openai":
        return _resolve_openai_backend()
    return _resolve_company_backend()


def _headers(session: BackendSession) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {session.api_key}",
        "Content-Type": "application/json",
    }
    if session.provider == "openai":
        if session.organization:
            headers["OpenAI-Organization"] = session.organization
        if session.project:
            headers["OpenAI-Project"] = session.project
    return headers


def _trim_incomplete_sentence(text: str) -> str:
    """Trim a *truncated* reply back to its last complete sentence.

    Only meaningful when the API reported ``finish_reason == "length"``. A
    punctuation-free but complete reply is never blanked out.
    """
    text = (text or "").strip()
    if not text or text[-1] in _SENTENCE_ENDINGS:
        return text
    last_idx = max((text.rfind(ch) for ch in _SENTENCE_ENDINGS), default=-1)
    return text[: last_idx + 1].strip() if last_idx != -1 else text


def _extract_content(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMAPIError("Malformed response: missing choices.")

    first = choices[0] if isinstance(choices[0], dict) else {}
    raw_message = first.get("message")
    message = raw_message if isinstance(raw_message, dict) else {}
    content = message.get("content")
    truncated = str(first.get("finish_reason") or "").strip().lower() == "length"

    def finalize(value: str) -> str:
        value = value.strip()
        return _trim_incomplete_sentence(value) if truncated else value

    if isinstance(content, str):
        return finalize(content)
    if isinstance(content, list):
        parts = [
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and str(item.get("type") or "").lower() == "text"
        ]
        if parts:
            return finalize("\n".join(part for part in parts if part))
    if isinstance(first.get("text"), str):
        return finalize(str(first["text"]))

    raise LLMAPIError("Malformed response: no assistant content found.")


def chat_completion(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    timeout: int | None = None,
    response_format_json: bool = False,
) -> dict[str, Any]:
    """One chat completion against the active backend.

    Returns ``{"content", "usage", "provider", "display_name"}``. Raises
    ``LLMNoKeyError`` / ``LLMAuthError`` / ``LLMAPIError`` — never a bare
    ``requests`` exception.
    """
    if os.environ.get("CRM_EAGLE_CONFIG"):
        from modules.ai_imaging.eagle_eye_remote.crm.provider import completion
        try:
            return completion(messages, model=model, max_tokens=max_tokens,
                              temperature=temperature, timeout=timeout,
                              response_format_json=response_format_json)
        except Exception as exc:
            raise LLMAPIError("Eagle Eye AI processing failed") from exc
    raise LLMNoKeyError("Hosted CRM requires the Eagle Eye AI gateway")

def test_connection(timeout: int = 15) -> dict[str, Any]:
    """Hosted diagnostics use the shared Brain and cannot select vendor credentials."""
    if os.environ.get('CRM_EAGLE_CONFIG'):
        from modules.ai_imaging.eagle_eye_remote.crm.provider import completion
        completion([{'role': 'user', 'content': 'Connection test'}], max_tokens=8, timeout=timeout)
        return {'ok': True, 'provider': 'eagle_eye', 'display_name': 'Eagle AI Brain'}
    raise LLMAuthError('Use Eagle AI Brain connection diagnostics on the server.')
