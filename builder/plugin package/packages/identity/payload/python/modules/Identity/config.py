"""Configuration resolution for the Identity module.

Resolves the ``config/identity`` directory (mirroring the Offline Cloud module's
``_config_root`` logic so behaviour matches dev vs frozen builds) and loads the
Google OAuth *installed-app* client configuration.

No third-party imports here — pure stdlib so this stays import-safe.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

GOOGLE_OAUTH_FILE = "google_oauth.json"
IDENTITY_FLAG_FILE = "identity.json"


def _config_root() -> Path:
    """Return the active config root.

    Mirrors ``PacsClient.utils.offline_cloud._config_root``: in a frozen build use
    the roaming config root; in development use ``PROJECT_ROOT/config``.
    """
    try:
        if getattr(sys, "frozen", False):
            from aipacs_runtime import roaming_config_root, seed_user_config_defaults

            seed_user_config_defaults()
            return Path(roaming_config_root())
        from _project_root import PROJECT_ROOT

        return Path(PROJECT_ROOT) / "config"
    except Exception as exc:  # pragma: no cover - last-resort fallback
        logger.debug("config root resolution fell back to home: %s", exc)
        return Path.home() / ".aipacs" / "config"


def identity_config_dir() -> Path:
    """Return (and create) the ``config/identity`` directory."""
    d = _config_root() / "identity"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pragma: no cover
        logger.debug("could not create identity config dir %s: %s", d, exc)
    return d


def identity_flag_file_path() -> Path:
    """Full path to the feature-flag file WITHOUT creating any directory.

    Used by the frequently-called feature-flag check so a *disabled* module performs
    zero filesystem side effects at startup.
    """
    return _config_root() / "identity" / IDENTITY_FLAG_FILE


def google_oauth_path() -> Path:
    return identity_config_dir() / GOOGLE_OAUTH_FILE


def load_google_client_config() -> dict | None:
    """Return the OAuth installed-app client config, or ``None`` if not set up.

    Accepts either a Google-Console "Desktop app" download (``{"installed": {...}}``
    or ``{"web": {...}}``) or a flat ``{client_id, client_secret, ...}`` which is
    wrapped as ``{"installed": {...}}`` for ``google-auth``.
    """
    p = google_oauth_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read Google OAuth client config %s: %s", p, exc)
        return None
    if not isinstance(data, dict):
        return None
    if "installed" in data or "web" in data:
        return data
    if "client_id" in data:
        return {"installed": data}
    return None


def google_client_configured() -> bool:
    return load_google_client_config() is not None
