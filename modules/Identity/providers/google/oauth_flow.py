"""Google OAuth 2.0 Authorization-Code + PKCE flow for a Desktop (installed) app.

Uses ``google-auth-oauthlib``'s ``InstalledAppFlow`` which implements the
Google-recommended desktop flow: opens the system browser and runs a one-shot
loopback HTTP server on an ephemeral port to receive the authorization code, with
PKCE applied by the library. **Blocking** — callers must run :func:`run_installed_app_flow`
off the Qt UI thread.

All heavy imports are local so importing this module is cheap and does not require
the google libraries to be installed.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# OpenID Connect + Drive (per-file) scopes. ``drive.file`` is non-sensitive and only
# grants access to files this app creates/opens — minimal verification burden.
DEFAULT_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive.file",
]

USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def run_installed_app_flow(client_config: dict, scopes: list[str] | None = None):
    """Run the loopback PKCE flow. Returns google ``Credentials``. BLOCKING."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(
        client_config, scopes=scopes or DEFAULT_SCOPES
    )
    # port=0 -> ephemeral loopback port; opens the system browser.
    creds = flow.run_local_server(
        port=0,
        open_browser=True,
        authorization_prompt_message="",
        success_message=(
            "AI-PACS: Google sign-in complete. You can close this tab and return "
            "to AI-PACS."
        ),
    )
    return creds


def fetch_userinfo(creds) -> dict:
    """Fetch the OIDC userinfo (sub, email, name, picture, email_verified)."""
    import requests

    resp = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {creds.token}"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def revoke_token(refresh_or_access_token: str) -> bool:
    """Best-effort revoke at Google. Returns True on HTTP 200."""
    import requests

    try:
        resp = requests.post(
            REVOKE_URL,
            params={"token": refresh_or_access_token},
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception as exc:
        logger.warning("Google token revoke failed: %s", exc)
        return False


def credentials_to_payload(creds) -> dict:
    """Serialize google ``Credentials`` to a JSON-safe payload for secure storage."""
    expiry = getattr(creds, "expiry", None)
    return {
        "token": getattr(creds, "token", None),
        "refresh_token": getattr(creds, "refresh_token", None),
        "token_uri": getattr(creds, "token_uri", None),
        "client_id": getattr(creds, "client_id", None),
        "client_secret": getattr(creds, "client_secret", None),
        "scopes": list(getattr(creds, "scopes", None) or []),
        "expiry": expiry.isoformat() if expiry else None,
    }


def payload_to_credentials(payload: dict):
    """Rebuild google ``Credentials`` from a stored payload (for later API calls)."""
    from google.oauth2.credentials import Credentials

    return Credentials(
        token=payload.get("token"),
        refresh_token=payload.get("refresh_token"),
        token_uri=payload.get("token_uri"),
        client_id=payload.get("client_id"),
        client_secret=payload.get("client_secret"),
        scopes=payload.get("scopes"),
    )
