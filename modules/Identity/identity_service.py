"""IdentityService — orchestrates external identities for the current AI-PACS user.

Pure Python (no Qt) so it is unit-testable headless. The UI layer wraps
:meth:`connect` in a worker thread because provider connect flows block (browser +
network).

The service NEVER touches the AI-PACS server login. It only reads the current
``auth_user`` dict to derive a link key and manages rows in ``external_identities``.
"""

from __future__ import annotations

import logging
from typing import Any

from modules.Identity.models import ExternalIdentity, ProviderInfo
from modules.Identity.registry import all_providers, get_provider

logger = logging.getLogger(__name__)


class IdentityService:
    def __init__(self, aipacs_user: str):
        self.aipacs_user = aipacs_user or "local"

    # ── link-key resolution ────────────────────────────────────────────────────
    @staticmethod
    def resolve_aipacs_user(auth_user: dict[str, Any] | None) -> str:
        """Derive the link key from the existing login's ``auth_user`` dict.

        Uses ``username`` (falls back to ``full_name``). Does not modify auth_user.
        """
        if not auth_user:
            return "local"
        return str(auth_user.get("username") or auth_user.get("full_name") or "local")

    # ── queries ────────────────────────────────────────────────────────────────
    def list_identities(self) -> list[ExternalIdentity]:
        from database import identity_db

        return identity_db.list_identities(self.aipacs_user)

    def list_provider_infos(self) -> list[ProviderInfo]:
        """Snapshot every provider's availability + connection state for the UI."""
        connected_by_provider: dict[str, ExternalIdentity] = {}
        try:
            for ident in self.list_identities():
                connected_by_provider.setdefault(ident.provider, ident)
        except Exception as exc:  # pragma: no cover - DB optional at view time
            logger.warning("listing linked identities failed: %s", exc)

        infos: list[ProviderInfo] = []
        for provider in all_providers():
            try:
                available, detail = provider.is_available()
            except Exception as exc:  # pragma: no cover - defensive
                available, detail = False, str(exc)
            linked = connected_by_provider.get(provider.id)
            infos.append(
                ProviderInfo(
                    id=provider.id,
                    display_name=provider.display_name,
                    capabilities=[c.value for c in provider.capabilities],
                    available=available,
                    detail=detail,
                    connected=linked is not None,
                    connected_handle=linked.handle if linked else "",
                    subject_id=linked.subject_id if linked else "",
                )
            )
        return infos

    # ── mutations ───────────────────────────────────────────────────────────────
    def connect(self, provider_id: str) -> ExternalIdentity:
        """Run a provider connect flow and link the identity. BLOCKING."""
        provider = get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Unknown identity provider: {provider_id!r}")
        identity = provider.connect(self.aipacs_user)

        from database import identity_db

        identity_db.upsert_identity(identity)
        return identity

    def disconnect(self, provider_id: str, subject_id: str) -> None:
        from database import identity_db

        identity = identity_db.get_identity(self.aipacs_user, provider_id, subject_id)
        provider = get_provider(provider_id)
        if provider is not None and identity is not None:
            try:
                provider.disconnect(identity)
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning("provider disconnect failed: %s", exc)
        identity_db.delete_identity(self.aipacs_user, provider_id, subject_id)

    def get_capability_client(self, provider_id: str, subject_id: str, capability):
        """Return a provider capability client (e.g. a Drive service) for a linked id.

        Used by the cloud_consultation module to obtain an authenticated transport
        without ever handling raw credentials itself.
        """
        from database import identity_db

        identity = identity_db.get_identity(self.aipacs_user, provider_id, subject_id)
        if identity is None:
            raise ValueError("That identity is not linked to this user.")
        provider = get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Unknown identity provider: {provider_id!r}")
        return provider.get_capability_client(identity, capability)
