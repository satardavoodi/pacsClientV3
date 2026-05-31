"""GoogleIdentityProvider — profile + Google Drive capability.

Connecting runs the loopback PKCE flow, fetches the OIDC profile, persists the
token securely, and returns an :class:`ExternalIdentity`. Disconnecting best-effort
revokes the token at Google and clears the stored secret.

The Drive capability client (a ``CloudTransport`` used by the consultation layer)
arrives in Phase 2; :meth:`get_capability_client` raises ``NotImplementedError`` for
now so nothing silently half-works.
"""

from __future__ import annotations

import logging

from modules.Identity.models import Capability, ExternalIdentity
from modules.Identity.providers.base import IdentityProvider

logger = logging.getLogger(__name__)


class GoogleIdentityProvider(IdentityProvider):
    id = "google"
    display_name = "Google"
    capabilities = {Capability.PROFILE, Capability.CLOUD_STORAGE}

    def is_available(self) -> tuple[bool, str]:
        try:
            import google_auth_oauthlib  # noqa: F401
            import google.oauth2.credentials  # noqa: F401
            import requests  # noqa: F401
        except Exception as exc:
            return False, (
                "Google libraries not installed (need google-auth, "
                f"google-auth-oauthlib, requests): {exc}"
            )
        from modules.Identity.config import google_client_configured, google_oauth_path

        if not google_client_configured():
            return False, (
                "Google OAuth client not configured. Add your Desktop-app client "
                f"JSON at: {google_oauth_path()}"
            )
        return True, "Ready to connect."

    def connect(self, aipacs_user: str) -> ExternalIdentity:
        ok, reason = self.is_available()
        if not ok:
            raise RuntimeError(reason)

        from modules.Identity.config import load_google_client_config
        from modules.Identity.secure_store import save_secret

        from .oauth_flow import (
            credentials_to_payload,
            fetch_userinfo,
            run_installed_app_flow,
        )

        client_config = load_google_client_config()
        creds = run_installed_app_flow(client_config)
        info = fetch_userinfo(creds)

        subject = str(info.get("sub") or info.get("id") or "").strip()
        if not subject:
            raise RuntimeError("Google did not return a stable account id (sub).")

        identity = ExternalIdentity(
            provider=self.id,
            subject_id=subject,
            handle=info.get("email", "") or "",
            display_name=info.get("name", "") or info.get("email", "") or "",
            avatar_url=info.get("picture", "") or "",
            capabilities=[c.value for c in self.capabilities],
            aipacs_user=aipacs_user,
            extra={"email_verified": bool(info.get("email_verified"))},
        )

        if not save_secret(self.id, subject, credentials_to_payload(creds)):
            logger.warning("Google token could not be stored securely for %s", subject)

        return identity

    def disconnect(self, identity: ExternalIdentity) -> None:
        from modules.Identity.secure_store import delete_secret, load_secret

        from .oauth_flow import revoke_token

        try:
            payload = load_secret(self.id, identity.subject_id)
            token = (payload or {}).get("refresh_token") or (payload or {}).get("token")
            if token:
                revoke_token(token)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Google revoke during disconnect failed: %s", exc)
        delete_secret(self.id, identity.subject_id)

    def get_credentials(self, identity: ExternalIdentity):
        """Load the stored token, refresh if needed, persist, and return Credentials.

        Raises ``RuntimeError`` if nothing is stored or refresh fails (the caller
        should prompt the user to reconnect the account).
        """
        from modules.Identity.secure_store import load_secret, save_secret

        from .oauth_flow import credentials_to_payload, payload_to_credentials

        payload = load_secret(self.id, identity.subject_id)
        if not payload:
            raise RuntimeError("No stored Google token; reconnect the account.")

        creds = payload_to_credentials(payload)
        try:
            if not getattr(creds, "valid", False) and getattr(creds, "refresh_token", None):
                from google.auth.transport.requests import Request

                creds.refresh(Request())
                save_secret(self.id, identity.subject_id, credentials_to_payload(creds))
        except Exception as exc:
            raise RuntimeError(f"Google token refresh failed; reconnect the account: {exc}")
        return creds

    def get_capability_client(self, identity: ExternalIdentity, cap: Capability):
        if cap == Capability.CLOUD_STORAGE:
            # A Drive v3 service; the cloud_consultation module wraps it in a
            # CloudTransport. Built from refreshed credentials.
            from googleapiclient.discovery import build

            creds = self.get_credentials(identity)
            return build("drive", "v3", credentials=creds, cache_discovery=False)
        return super().get_capability_client(identity, cap)
