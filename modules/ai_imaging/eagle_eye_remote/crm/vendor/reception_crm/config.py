from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOG = logging.getLogger("reception_crm.config")


# One definition, in runtime.py, so the packaged service and this module cannot
# disagree about where data goes. See runtime.DEFAULT_DATA_ROOT for why it is no
# longer a hardcoded drive letter and one clinic's name.
from .runtime import DEFAULT_DATA_ROOT  # noqa: E402  (re-exported for callers)

DEFAULT_CONFIG_PATHS = (
    Path("config/endpoints.json"),
    DEFAULT_DATA_ROOT / "config" / "endpoints.json",
    Path("config/endpoints.example.json"),
)


@dataclass(frozen=True)
class AuthConfig:
    mode: str = "none"
    token_env: str = "RECEPTION_CRM_API_TOKEN"
    api_key_env: str = "RECEPTION_CRM_API_KEY"
    api_key_header: str = "X-API-Key"


@dataclass(frozen=True)
class ApiConfig:
    base_url: str
    timeout_seconds: int = 60
    auth: AuthConfig = field(default_factory=AuthConfig)
    default_headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EndpointConfig:
    name: str
    method: str
    path: str
    params: dict[str, Any] = field(default_factory=dict)
    date_filter: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AppConfig:
    data_root: Path
    api: ApiConfig
    endpoints: list[EndpointConfig]
    config_path: Path


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def discover_config_path(explicit_path: str | None = None) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file was not found: {path}")
        return path

    env_path = os.getenv("RECEPTION_CRM_CONFIG")
    if env_path:
        path = Path(env_path)
        if not path.exists():
            raise FileNotFoundError(f"RECEPTION_CRM_CONFIG points to a missing file: {path}")
        return path

    for path in DEFAULT_CONFIG_PATHS:
        if path.exists():
            return path

    raise FileNotFoundError("No CRM endpoint config found.")


def _active_profile_or_warn():
    """The operator's saved connection profile, or None — but never in silence.

    `load_settings()` does not raise when there is no settings file; it builds a
    profile from the environment. It raises when the file EXISTS and cannot be
    read: malformed JSON from an interrupted save, or a profile carrying a key
    this build does not know, which is what a downgrade looks like.

    So the failures this catches all mean "the operator configured a centre and
    we could not read which one", and the fallback below quietly resolves the
    base URL from the environment instead — where the default host is a literal
    belonging to one particular clinic. Swallowed, that turns an unreadable
    settings file into the agent talking to somebody else's CRM, with nothing
    anywhere saying so.

    The fallback is kept, because refusing to start over a malformed settings
    file would be a worse failure on a clinic morning. What changes is that it
    can now be found: the fault is logged, loudly, with the path.
    """
    try:
        from .settings import load_settings, settings_path
    except ImportError:  # pragma: no cover - settings is part of the package
        return None

    try:
        return load_settings().active()
    except Exception as exc:  # noqa: BLE001 - reported, then degraded deliberately
        LOG.error(
            "Could not read connection settings at %s (%s: %s). Falling back to "
            "environment and config-file values, which may point at a DIFFERENT "
            "centre than the one configured.",
            settings_path(), type(exc).__name__, exc,
        )
        return None


def load_config(explicit_path: str | None = None) -> AppConfig:
    path = discover_config_path(explicit_path)
    raw = _read_json(path)
    active_profile = _active_profile_or_warn()

    api_raw = raw.get("api", {})
    auth_raw = api_raw.get("auth", {})
    profile_base_url = active_profile.crm_base_url if active_profile else None
    base_url = os.getenv("RECEPTION_CRM_BASE_URL") or profile_base_url or api_raw.get("base_url")
    if not base_url:
        raise ValueError("CRM API base_url is required in config or RECEPTION_CRM_BASE_URL.")

    profile_data_root = active_profile.data_root if active_profile else None
    data_root = Path(os.getenv("RECEPTION_CRM_DATA_ROOT") or profile_data_root or raw.get("data_root") or DEFAULT_DATA_ROOT)
    endpoints = [
        EndpointConfig(
            name=item["name"],
            method=item.get("method", "GET").upper(),
            path=item["path"],
            params=item.get("params", {}),
            date_filter=item.get("date_filter", {}),
        )
        for item in raw.get("endpoints", [])
    ]

    return AppConfig(
        data_root=data_root,
        api=ApiConfig(
            base_url=base_url.rstrip("/"),
            timeout_seconds=int(api_raw.get("timeout_seconds", 60)),
            auth=AuthConfig(
                mode=auth_raw.get("mode", "none").lower(),
                token_env=auth_raw.get("token_env", "RECEPTION_CRM_API_TOKEN"),
                api_key_env=auth_raw.get("api_key_env", "RECEPTION_CRM_API_KEY"),
                api_key_header=auth_raw.get("api_key_header", "X-API-Key"),
            ),
            default_headers=dict(api_raw.get("default_headers", {})),
        ),
        endpoints=endpoints,
        config_path=path,
    )
