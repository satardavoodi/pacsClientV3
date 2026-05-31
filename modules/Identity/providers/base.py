"""The :class:`IdentityProvider` abstraction.

A provider represents one *kind* of external account a user can connect (Google,
Telegram, Instagram, ...). It is intentionally broader than cloud storage so future
providers slot in without changing consultation code. The consultation layer obtains
capability clients (e.g. a Drive transport) via :meth:`get_capability_client` — it
never reaches for raw credentials itself.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from modules.Identity.models import Capability, ExternalIdentity


class IdentityProvider(ABC):
    id: str = ""
    display_name: str = ""
    capabilities: set[Capability] = set()

    @abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """Return ``(ok, reason)``: whether deps are installed AND configured."""
        raise NotImplementedError

    @abstractmethod
    def connect(self, aipacs_user: str) -> ExternalIdentity:
        """Run the provider's connect flow and return the linked identity.

        BLOCKING (may open a browser / network). Callers must run this off the Qt
        UI thread.
        """
        raise NotImplementedError

    @abstractmethod
    def disconnect(self, identity: ExternalIdentity) -> None:
        """Revoke (best-effort) and remove stored credentials for an identity."""
        raise NotImplementedError

    def get_capability_client(self, identity: ExternalIdentity, cap: Capability):
        """Return a client object for a capability (e.g. a Drive transport).

        Default: not implemented. Providers override for the capabilities they
        advertise.
        """
        raise NotImplementedError(
            f"{self.id!r} does not provide capability {getattr(cap, 'value', cap)!r}"
        )
