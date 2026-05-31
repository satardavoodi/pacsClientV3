"""Provider registry.

Providers register themselves here; the UI and services discover them through
:func:`all_providers` / :func:`get_provider`. Default providers are registered
lazily and defensively so a missing optional dependency for one provider never
breaks the others.
"""

from __future__ import annotations

import logging

from modules.Identity.providers.base import IdentityProvider

logger = logging.getLogger(__name__)

_PROVIDERS: dict[str, IdentityProvider] = {}
_initialized = False


def register_provider(provider: IdentityProvider) -> None:
    _PROVIDERS[provider.id] = provider


def _ensure_default_providers() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True
    try:
        from modules.Identity.providers.google.provider import GoogleIdentityProvider

        register_provider(GoogleIdentityProvider())
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Google identity provider could not be registered: %s", exc)
    # Future providers (registered when implemented):
    #   from modules.Identity.providers.telegram.provider import TelegramIdentityProvider
    #   from modules.Identity.providers.instagram.provider import InstagramIdentityProvider


def get_provider(provider_id: str) -> IdentityProvider | None:
    _ensure_default_providers()
    return _PROVIDERS.get(provider_id)


def all_providers() -> list[IdentityProvider]:
    _ensure_default_providers()
    return list(_PROVIDERS.values())


def reset_for_tests() -> None:
    """Clear registry state (used by unit tests)."""
    global _initialized
    _PROVIDERS.clear()
    _initialized = False
