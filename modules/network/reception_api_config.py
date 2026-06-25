# -*- coding: utf-8 -*-
"""Reception / Workflow REST API endpoint configuration.

This is the **second** server channel of AI-PACS and is intentionally kept
*separate* from the PACS imaging socket channel:

* PACS / imaging socket channel  -> ``modules/network/socket_config.py``
  (patient list, thumbnails, DICOM metadata, download, viewer; port 50052).
* Reception / Workflow REST API  -> *this module*
  (admission/reception data, report metadata, reporting physician,
  approvals, comments, workflow state; default port 8080).

Do NOT mix the two. The socket port (50052) and the Reception/API port
(8080) are different services on (possibly) different hosts.

Resolution precedence for the Reception/API base URL:

1. Environment override ``AIPACS_RECEPTION_BASE_URL`` / ``RECEPTION_API_BASE_URL``
   (kept for backwards compatibility with existing deployments / CI).
2. Configured value from ``config/reception_api_config.json``
   (explicit ``reception_api_base_url`` field, else composed
   ``scheme://host:port``).
3. Hard-coded default ``http://81.16.117.196:8080`` (so existing
   installations with no config file keep working unchanged).

Authentication note: the Reception/API uses the SAME logged-in user
credentials/token as the PACS socket channel. Callers that need auth should
reuse ``modules.network.socket_token_manager.get_socket_token_manager()``.
This module deliberately stores NO passwords or tokens.
"""

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from PacsClient.utils.config import SOCKET_CONFIG_PATH
except Exception:  # pragma: no cover - extremely defensive
    from pathlib import Path
    SOCKET_CONFIG_PATH = Path.cwd() / "config"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_SCHEME = "http"
_DEFAULT_HOST = "81.16.117.196"
_DEFAULT_PORT = 8080
_DEFAULT_BASE_URL = f"{_DEFAULT_SCHEME}://{_DEFAULT_HOST}:{_DEFAULT_PORT}"
_DEFAULT_TIMEOUT = 8

# Environment override keys (highest precedence). These already existed in the
# hydration / report code paths before this config was introduced, so they are
# preserved here to avoid breaking any deployment that relies on them.
_ENV_OVERRIDE_KEYS = ("AIPACS_RECEPTION_BASE_URL", "RECEPTION_API_BASE_URL")

_CONFIG_FILENAME = "reception_api_config.json"


class ReceptionApiConfig:
    """Configuration manager for the Reception / Workflow REST API endpoint."""

    def __init__(self, config_path: Optional[str] = None):
        try:
            if config_path is None:
                config_dir = SOCKET_CONFIG_PATH
                os.makedirs(config_dir, exist_ok=True)
                config_path = os.path.join(str(config_dir), _CONFIG_FILENAME)

            self.config_path = config_path
            self.config = self._load_default_config()
            self._load_config()
            logger.info("Reception API config initialized: %s", config_path)
        except Exception as exc:
            logger.error("Failed to initialize ReceptionApiConfig: %s", exc)
            self.config = self._load_default_config()
            self.config_path = config_path or _CONFIG_FILENAME

    # -- defaults ----------------------------------------------------------
    def _load_default_config(self) -> Dict[str, Any]:
        return {
            # ``reception_api_base_url`` is the authoritative field. When it is
            # a non-empty string it wins over scheme/host/port. The Settings UI
            # edits this field directly.
            "reception_api_base_url": _DEFAULT_BASE_URL,
            # Structured fallback (used only when base_url is blank).
            "reception_api_scheme": _DEFAULT_SCHEME,
            "reception_api_host": _DEFAULT_HOST,
            "reception_api_port": _DEFAULT_PORT,
            # REST request timeout (seconds) for Reception/API calls.
            "request_timeout": _DEFAULT_TIMEOUT,
        }

    # -- load / save -------------------------------------------------------
    def _load_config(self) -> None:
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as fh:
                    file_config = json.load(fh)
                if isinstance(file_config, dict):
                    self.config.update(file_config)
                    logger.info("Loaded Reception API config from %s", self.config_path)
            else:
                logger.info("Creating default Reception API config at %s", self.config_path)
                try:
                    self.save_config()
                except Exception as save_error:
                    logger.warning("Could not save default Reception API config: %s", save_error)
        except Exception as exc:
            logger.error("Error loading Reception API config: %s", exc)
            logger.info("Using default Reception API configuration")

    def save_config(self) -> None:
        try:
            config_dir = os.path.dirname(self.config_path)
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as fh:
                json.dump(self.config, fh, indent=2, ensure_ascii=False)
            logger.info("Saved Reception API config to %s", self.config_path)
        except PermissionError:
            logger.warning("Cannot save Reception API config - file is read-only: %s", self.config_path)
        except Exception as exc:
            logger.error("Error saving Reception API config: %s", exc)

    # -- accessors ---------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.config[key] = value

    def get_base_url(self) -> str:
        """Return the configured Reception/API base URL (no trailing slash).

        The explicit ``reception_api_base_url`` field wins. When it is blank
        the URL is composed from ``scheme``/``host``/``port``. If the host
        field itself contains a scheme it is accepted as a full URL.
        """
        explicit = str(self.get("reception_api_base_url", "") or "").strip()
        if explicit:
            return explicit.rstrip("/")

        scheme = str(self.get("reception_api_scheme", _DEFAULT_SCHEME) or _DEFAULT_SCHEME).strip()
        scheme = scheme or _DEFAULT_SCHEME
        host = str(self.get("reception_api_host", _DEFAULT_HOST) or _DEFAULT_HOST).strip()
        host = host or _DEFAULT_HOST

        port_raw = self.get("reception_api_port", _DEFAULT_PORT)
        try:
            port = int(port_raw)
        except Exception:
            port = _DEFAULT_PORT

        if "://" in host:
            # User pasted a full URL into the host field - accept gracefully.
            return host.rstrip("/")
        return f"{scheme}://{host}:{port}".rstrip("/")

    def get_request_timeout(self) -> int:
        timeout = self.get("request_timeout", _DEFAULT_TIMEOUT)
        try:
            timeout = int(timeout)
        except Exception:
            return _DEFAULT_TIMEOUT
        return timeout if timeout > 0 else _DEFAULT_TIMEOUT

    def set_base_url(self, base_url: str, save_to_file: bool = True) -> None:
        """Persist a new Reception/API base URL (edited from Settings UI)."""
        cleaned = str(base_url or "").strip().rstrip("/")
        self.set("reception_api_base_url", cleaned)
        # Keep the structured host/port fields roughly in sync for transparency.
        try:
            from urllib.parse import urlparse

            probe = cleaned if "://" in cleaned else f"http://{cleaned}"
            parsed = urlparse(probe)
            if parsed.scheme:
                self.set("reception_api_scheme", parsed.scheme)
            if parsed.hostname:
                self.set("reception_api_host", parsed.hostname)
            if parsed.port:
                self.set("reception_api_port", int(parsed.port))
        except Exception:
            pass
        if save_to_file:
            self.save_config()
        logger.info("Updated Reception API base URL: %s", cleaned)

    def get_all_config(self) -> Dict[str, Any]:
        return dict(self.config)


# ---------------------------------------------------------------------------
# Global accessors
# ---------------------------------------------------------------------------
_reception_api_config: Optional[ReceptionApiConfig] = None


def get_reception_api_config() -> ReceptionApiConfig:
    """Return the global :class:`ReceptionApiConfig` singleton."""
    global _reception_api_config
    if _reception_api_config is None:
        _reception_api_config = ReceptionApiConfig()
    return _reception_api_config


def reload_reception_api_config() -> ReceptionApiConfig:
    """Force a fresh reload from disk (used after the Settings UI saves)."""
    global _reception_api_config
    _reception_api_config = ReceptionApiConfig()
    return _reception_api_config


def get_reception_api_base_url() -> str:
    """Resolve the Reception/Workflow API base URL for REST callers.

    Precedence: environment override -> config file -> hard-coded default.
    Always returns a non-empty string with no trailing slash.
    """
    # 1) Environment override (existing deployments / CI).
    for key in _ENV_OVERRIDE_KEYS:
        value = (os.environ.get(key) or "").strip()
        if value:
            return value.rstrip("/")

    # 2) Active server profile (multi-server): the Reception / Workflow API
    #    follows the active center when profiles are enabled and the slot is
    #    configured. Falls through to the shared config file when off / unset.
    try:
        from PacsClient.utils.server_profiles import active_module_endpoint

        endpoint = active_module_endpoint("reception_api")
        if endpoint:
            endpoint = endpoint.strip().rstrip("/")
            if endpoint and "://" not in endpoint:
                endpoint = "http://" + endpoint
            if endpoint:
                return endpoint
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Per-profile reception endpoint unavailable: %s", exc)

    # 3) Configured value.
    try:
        configured = get_reception_api_config().get_base_url()
        if configured:
            return configured
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Reception API config unavailable, using default: %s", exc)

    # 4) Hard-coded default.
    return _DEFAULT_BASE_URL


def get_reception_api_timeout() -> int:
    """Resolve the REST request timeout (seconds) for Reception/API calls."""
    try:
        return get_reception_api_config().get_request_timeout()
    except Exception:
        return _DEFAULT_TIMEOUT


# ---------------------------------------------------------------------------
# Reception/API circuit breaker (added 2026-06-26)
# ---------------------------------------------------------------------------
# When a center's Reception/Workflow REST API is unreachable (e.g. the Mehr
# server has no reception service on its configured port, or a poor link drops
# the connection), the post-search reporting-physician hydration and report
# lookups re-hit the dead endpoint on EVERY search — hundreds of ConnectionError
# / timeout failures that waste the (already thin, on a poor link) bandwidth and
# spam the logs (observed: 426 reporter-hydration rest_errors against
# http://5.57.36.202:8800 in one Mehr session). The breaker short-circuits REST
# callers after a few consecutive failures for a cooldown, then half-opens to
# probe once and self-heals on the next success. It is keyed by base_url, so
# switching centers (Razi <-> Mehr) keeps independent breaker state and a healthy
# center is never penalised for a sick sibling. Background/non-clinical only —
# this NEVER touches the imaging socket channel or the download path. Reversible:
# AIPACS_RECEPTION_BREAKER=0 restores the prior always-try behavior.
_RECEPTION_BREAKER_ENABLED = (os.environ.get("AIPACS_RECEPTION_BREAKER", "1") or "1").strip() != "0"
try:
    _RECEPTION_BREAKER_THRESHOLD = max(1, int(os.environ.get("AIPACS_RECEPTION_BREAKER_FAILS", "3")))
except ValueError:
    _RECEPTION_BREAKER_THRESHOLD = 3
try:
    _RECEPTION_BREAKER_COOLDOWN_S = max(5.0, float(os.environ.get("AIPACS_RECEPTION_BREAKER_COOLDOWN", "180")))
except ValueError:
    _RECEPTION_BREAKER_COOLDOWN_S = 180.0

import threading as _threading
import time as _time

_reception_breaker_lock = _threading.Lock()
# base_url -> {"failures": int, "open_until": float, "logged": bool}
_reception_breaker_state: Dict[str, Dict[str, Any]] = {}


def _breaker_key(base_url: Optional[str]) -> str:
    if base_url:
        return str(base_url).strip().rstrip("/")
    try:
        return get_reception_api_base_url()
    except Exception:
        return _DEFAULT_BASE_URL


def reception_api_breaker_open(base_url: Optional[str] = None) -> bool:
    """Return True when REST callers should SKIP this center's Reception/API
    (the breaker is open during its cooldown). Returns False — i.e. allow the
    call — when the breaker is disabled, has never tripped, or is half-open
    (cooldown elapsed) so exactly one probe gets through to self-heal."""
    if not _RECEPTION_BREAKER_ENABLED:
        return False
    key = _breaker_key(base_url)
    now = _time.monotonic()
    with _reception_breaker_lock:
        st = _reception_breaker_state.get(key)
        if not st:
            return False
        return now < float(st.get("open_until", 0.0) or 0.0)


def record_reception_api_failure(base_url: Optional[str] = None) -> None:
    """Record a failed Reception/API REST call. Opens the breaker once
    consecutive failures reach the threshold."""
    if not _RECEPTION_BREAKER_ENABLED:
        return
    key = _breaker_key(base_url)
    now = _time.monotonic()
    with _reception_breaker_lock:
        st = _reception_breaker_state.setdefault(
            key, {"failures": 0, "open_until": 0.0, "logged": False})
        st["failures"] = int(st.get("failures", 0)) + 1
        if st["failures"] >= _RECEPTION_BREAKER_THRESHOLD:
            st["open_until"] = now + _RECEPTION_BREAKER_COOLDOWN_S
            if not st.get("logged"):
                st["logged"] = True
                logger.warning(
                    "[reception-breaker] OPEN for %s after %d consecutive failures — "
                    "skipping Reception/API REST calls for %.0fs (set AIPACS_RECEPTION_BREAKER=0 "
                    "to disable)", key, st["failures"], _RECEPTION_BREAKER_COOLDOWN_S,
                )


def record_reception_api_success(base_url: Optional[str] = None) -> None:
    """Record a successful Reception/API REST call — closes the breaker (self-heal)."""
    if not _RECEPTION_BREAKER_ENABLED:
        return
    key = _breaker_key(base_url)
    with _reception_breaker_lock:
        st = _reception_breaker_state.get(key)
        if st and (st.get("failures") or st.get("open_until")):
            if st.get("logged"):
                logger.info("[reception-breaker] CLOSED for %s (Reception/API reachable again)", key)
            _reception_breaker_state[key] = {"failures": 0, "open_until": 0.0, "logged": False}
