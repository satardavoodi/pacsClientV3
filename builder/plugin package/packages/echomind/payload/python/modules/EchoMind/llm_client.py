"""
Provider-aware EchoMind LLM gateway.

This module keeps the legacy ``gapgpt_chat`` public API for compatibility,
but it now routes requests through either:

1. The existing company GapGPT path (default)
2. A user-configured OpenAI path
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

from modules.EchoMind.ai_chat_config import GAPGPT_API_URL, GAPGPT_DEFAULT_MODEL, GAPGPT_TIMEOUT
from modules.EchoMind.settings_store import get_echomind_api_key, get_llm_backend, get_openai_settings, get_proxy_settings

log = logging.getLogger(__name__)

_API_URL = GAPGPT_API_URL
_DEFAULT_MODEL = GAPGPT_DEFAULT_MODEL
_DEFAULT_TIMEOUT = GAPGPT_TIMEOUT


def _get_requests_proxies() -> "dict[str, str] | None":
    """Return a requests-compatible proxies dict when SOCKS5 proxy is configured, else None."""
    try:
        cfg = get_proxy_settings()
        if cfg.get("connection_type") != "socks5":
            return None
        port = int(cfg.get("proxy_port") or 2080)
        proxy_url = f"socks5://127.0.0.1:{port}"
        return {"http": proxy_url, "https": proxy_url}
    except Exception:
        return None


def _ensure_socks_proxy_support(proxies: "dict[str, str] | None") -> None:
    if not proxies:
        return
    try:
        import socks  # type: ignore  # noqa: F401
    except Exception as exc:
        raise LLMAPIError(
            "SOCKS5 proxy is selected, but SOCKS support is unavailable in this Python environment. "
            "Install requests[socks] / PySocks for proxy-based OpenAI connections."
        ) from exc


class LLMError(Exception):
    """Base class for all EchoMind LLM gateway errors."""


class LLMNoKeyError(LLMError):
    """No usable backend key is configured for the selected EchoMind provider."""


class LLMAuthError(LLMError):
    """The selected provider rejected the request with an authentication error."""


class LLMAPIError(LLMError):
    """The selected provider returned a non-success response or malformed data."""


@dataclass(frozen=True)
class BackendSession:
    provider: str
    display_name: str
    api_key: str
    api_url: str
    organization: str = ""
    project: str = ""


def _active_backend() -> str:
    return "openai" if get_llm_backend() == "openai" else "company"


def is_active_backend_configured() -> bool:
    backend = _active_backend()
    if backend == "openai":
        return bool(str(get_openai_settings().get("api_key") or "").strip())
    return bool(str(get_echomind_api_key() or "").strip())


def get_active_backend_display_name() -> str:
    if _active_backend() == "openai":
        return "OpenAI"
    try:
        from modules.EchoMind.api_manager import Manage

        return Manage.instance().get_detected_center_display() or "EchoMind"
    except Exception:
        return "EchoMind"


def _resolve_company_backend() -> BackendSession:
    try:
        from modules.EchoMind.api_manager import APIKeyManager, Manage

        manager = APIKeyManager.instance()
        if not manager.is_validated():
            saved_key = (get_echomind_api_key() or "").strip()
            if not saved_key:
                raise LLMNoKeyError(
                    "No EchoMind credential is configured. Open Settings -> EchoMind and authenticate."
                )
            ok, _center, error = manager.validate_key(saved_key)
            if not ok:
                raise LLMAuthError(error or "The saved EchoMind credential is invalid.")
            try:
                Manage.instance().detect_center(saved_key)
            except Exception:
                pass

        center, key = Manage.instance().get_center_and_gapgpt_key()
        if not key or not key.strip():
            raise LLMNoKeyError(
                "No GapGPT key resolved. Open Settings -> EchoMind and authenticate."
            )
        return BackendSession(
            provider="company",
            display_name=center or "EchoMind",
            api_key=key.strip(),
            api_url=_API_URL,
        )
    except LLMError:
        raise
    except Exception as exc:
        raise LLMNoKeyError(
            f"Could not resolve the EchoMind company backend: {exc}"
        ) from exc


def _resolve_openai_backend(api_key_override: str | None = None) -> BackendSession:
    cfg = get_openai_settings()
    api_key = str(api_key_override or cfg.get("api_key") or "").strip()
    if not api_key:
        raise LLMNoKeyError(
            "No OpenAI API key is configured. Open Settings -> EchoMind -> OpenAI."
        )

    base_url = str(cfg.get("base_url") or "https://api.openai.com/v1").strip()
    if not base_url:
        base_url = "https://api.openai.com/v1"

    return BackendSession(
        provider="openai",
        display_name="OpenAI",
        api_key=api_key,
        api_url=base_url.rstrip("/") + "/chat/completions",
        organization=str(cfg.get("organization") or "").strip(),
        project=str(cfg.get("project") or "").strip(),
    )


def _resolve_active_backend(api_key_override: str | None = None) -> BackendSession:
    if _active_backend() == "openai" or api_key_override:
        return _resolve_openai_backend(api_key_override=api_key_override)
    return _resolve_company_backend()


def _openai_headers(session: BackendSession) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {session.api_key}",
        "Content-Type": "application/json",
    }
    if session.organization:
        headers["OpenAI-Organization"] = session.organization
    if session.project:
        headers["OpenAI-Project"] = session.project
    return headers


def _coerce_openai_content(content: Any) -> Any:
    if not isinstance(content, list):
        return content

    out: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = str(part.get("type") or "").strip().lower()
        if kind == "text":
            out.append({"type": "text", "text": str(part.get("text") or "")})
            continue
        if kind == "image":
            raw = str(part.get("image") or "").strip()
            if not raw:
                continue
            if raw.startswith("data:"):
                data_url = raw
            else:
                data_url = f"data:image/jpeg;base64,{raw}"
            out.append({"type": "image_url", "image_url": {"url": data_url}})
            continue
        out.append(part)
    return out or content


def _coerce_messages_for_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coerced: list[dict[str, Any]] = []
    for message in messages:
        coerced.append(
            {
                "role": str(message.get("role") or "user"),
                "content": _coerce_openai_content(message.get("content")),
            }
        )
    return coerced


def _extract_content_from_body(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMAPIError("Malformed response: missing choices.")

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").lower() == "text":
                text_parts.append(str(item.get("text") or ""))
        if text_parts:
            return "\n".join(x for x in text_parts if x).strip()

    text_value = first.get("text")
    if isinstance(text_value, str):
        return text_value.strip()

    raise LLMAPIError("Malformed response: no assistant content found.")


def _log_usage_company(model: str, prompt_tokens: int, completion_tokens: int, user_msg: str) -> None:
    try:
        from modules.EchoMind.api_manager import Manage

        Manage.instance().update_usage(
            model.strip() or _DEFAULT_MODEL,
            int(prompt_tokens or 0),
            int(completion_tokens or 0),
        )
    except Exception:
        pass


def _log_usage_openai(
    api_key: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    total = int(prompt_tokens or 0) + int(completion_tokens or 0)
    if total <= 0:
        return
    try:
        from PacsClient.utils.database import add_api_token_usage_delta, add_token_usage_delta

        add_api_token_usage_delta(
            api_key=api_key,
            center_name="OpenAI",
            model_name=model.strip() or "Unknown",
            tokens_delta=total,
        )
        add_token_usage_delta(
            center="OpenAI",
            model=model.strip() or "Unknown",
            tokens_delta=total,
        )
    except Exception:
        pass


def _log_usage(
    session: BackendSession,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    user_msg: str,
) -> None:
    if session.provider == "openai":
        _log_usage_openai(
            api_key=session.api_key,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    else:
        _log_usage_company(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            user_msg=user_msg,
        )


def chat_completion(
    messages: list[dict[str, Any]],
    *,
    model: str = _DEFAULT_MODEL,
    max_tokens: int | None = None,
    temperature: float = 0.0,
    timeout: int = _DEFAULT_TIMEOUT,
    api_key_override: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    session = _resolve_active_backend(api_key_override=api_key_override)
    resolved_model = str(model or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
    }
    if temperature is not None:
        payload["temperature"] = float(temperature)
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    headers = {
        "Authorization": f"Bearer {session.api_key}",
        "Content-Type": "application/json",
    }

    payload["messages"] = _coerce_messages_for_openai(messages)

    if session.provider == "openai":
        headers = _openai_headers(session)
        if reasoning_effort:
            payload["reasoning_effort"] = str(reasoning_effort).strip()

    try:
        resp = requests.post(session.api_url, json=payload, headers=headers, timeout=timeout, proxies=_get_requests_proxies())
    except requests.exceptions.RequestException as exc:
        raise LLMAPIError(
            f"Network error contacting {session.display_name}: {exc}"
        ) from exc

    if resp.status_code in (401, 403):
        raise LLMAuthError(
            f"{session.display_name} rejected the request. Check the configured API key."
        )

    if resp.status_code != 200:
        snippet = (resp.text or "")[:300].replace("\n", " ")
        raise LLMAPIError(
            f"{session.display_name} HTTP {resp.status_code}: {snippet}"
        )

    try:
        body: dict[str, Any] = resp.json()
    except Exception as exc:
        raise LLMAPIError(f"Malformed response body: {exc}") from exc

    content = _extract_content_from_body(body)
    usage = body.get("usage") or {}

    user_msg = next(
        (str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    _log_usage(
        session=session,
        model=resolved_model,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        user_msg=user_msg[:500],
    )

    log.debug(
        "chat_completion ok | provider=%s model=%s prompt_tokens=%s completion_tokens=%s",
        session.provider,
        resolved_model,
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
    )
    return {
        "content": content,
        "usage": {
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0))
            or (int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0))),
            "model": resolved_model,
            "center": session.display_name,
            "provider": session.provider,
        },
        "provider": session.provider,
        "display_name": session.display_name,
        "raw": body,
    }


def gapgpt_chat(
    messages: list[dict[str, Any]],
    *,
    model: str = _DEFAULT_MODEL,
    max_tokens: int | None = None,
    temperature: float = 0.0,
    timeout: int = _DEFAULT_TIMEOUT,
    reasoning_effort: str | None = None,
) -> str:
    return str(
        chat_completion(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            reasoning_effort=reasoning_effort,
        ).get("content")
        or ""
    ).strip()


def test_openai_connection(
    *,
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    organization: str = "",
    project: str = "",
    timeout: int = 15,
) -> dict[str, Any]:
    resolved_api_key = str(api_key or "").strip()
    if not resolved_api_key:
        raise LLMNoKeyError("No OpenAI API key is configured.")

    resolved_base_url = str(base_url or "https://api.openai.com/v1").strip().rstrip("/") or "https://api.openai.com/v1"
    proxies = _get_requests_proxies()
    _ensure_socks_proxy_support(proxies)

    headers = {
        "Authorization": f"Bearer {resolved_api_key}",
        "Content-Type": "application/json",
    }
    if str(organization or "").strip():
        headers["OpenAI-Organization"] = str(organization).strip()
    if str(project or "").strip():
        headers["OpenAI-Project"] = str(project).strip()

    try:
        resp = requests.get(
            f"{resolved_base_url}/models",
            headers=headers,
            timeout=int(timeout or 15),
            proxies=proxies,
        )
    except requests.exceptions.RequestException as exc:
        raise LLMAPIError(f"Connection test failed: {exc}") from exc

    if resp.status_code in (401, 403):
        raise LLMAuthError("Authentication failed. Check the configured key and project settings.")
    if resp.status_code >= 400:
        snippet = (resp.text or "")[:240].replace("\n", " ")
        raise LLMAPIError(f"Connection test failed with HTTP {resp.status_code}: {snippet}")

    return {
        "ok": True,
        "provider": "openai",
        "display_name": "OpenAI",
    }


def test_active_backend_connection(timeout: int = 15) -> dict[str, Any]:
    session = _resolve_active_backend()
    if session.provider == "openai":
        return test_openai_connection(
            api_key=session.api_key,
            base_url=session.api_url.rsplit("/", 2)[0],
            organization=session.organization,
            project=session.project,
            timeout=timeout,
        )
    else:
        url = _API_URL
        headers = {"Authorization": f"Bearer {session.api_key}", "Content-Type": "application/json"}

    proxies = _get_requests_proxies()
    _ensure_socks_proxy_support(proxies)

    try:
        resp = requests.post(
            url,
            headers=headers,
            json={
                "model": _DEFAULT_MODEL,
                "messages": [{"role": "user", "content": "Ping"}],
                "max_tokens": 8,
                "temperature": 0.0,
            },
            timeout=timeout,
            proxies=proxies,
        )
    except requests.exceptions.RequestException as exc:
        raise LLMAPIError(f"Connection test failed: {exc}") from exc

    if resp.status_code in (401, 403):
        raise LLMAuthError("Authentication failed. Check the configured key and project settings.")
    if resp.status_code >= 400:
        snippet = (resp.text or "")[:240].replace("\n", " ")
        raise LLMAPIError(f"Connection test failed with HTTP {resp.status_code}: {snippet}")

    return {
        "ok": True,
        "provider": session.provider,
        "display_name": session.display_name,
    }
