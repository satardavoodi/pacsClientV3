from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .runtime import DEFAULT_DATA_ROOT


APP_DIR_NAME = "Reception CRM Agent"
SETTINGS_FILE_NAME = "settings.json"

# The deployment's center name is supplied per-site via configuration or the
# RECEPTION_CENTER / RECEPTION_HTTP_API_CENTER environment variables. It is
# intentionally NOT hard-coded to any specific clinic (for example "RAZI"), so
# the same software can serve every center. DEFAULT_CENTER is only a neutral
# placeholder used when no center has been configured yet.
DEFAULT_CENTER = "DEFAULT"


def resolve_center(explicit: str | None = None) -> str:
    """Resolve the active center name.

    Precedence: an explicit value, then the RECEPTION_CENTER environment
    variable, then RECEPTION_HTTP_API_CENTER, then the neutral placeholder.
    No specific center name is baked into the code; each center supplies its
    own name through configuration.
    """
    return (
        (explicit or "").strip()
        or os.getenv("RECEPTION_CENTER")
        or os.getenv("RECEPTION_HTTP_API_CENTER")
        or DEFAULT_CENTER
    )


@dataclass
class ConnectionProfile:
    name: str = "default"
    center: str = field(default_factory=resolve_center)
    host: str = "81.16.117.196"
    crm_port: int = 8080
    dashboard_port: int = 80
    pacs_port: int = 8000
    socket_port: int = 50052
    username: str = ""
    password: str = ""
    password_env: str = "INO_PASS"
    data_root: str = field(default_factory=lambda: str(DEFAULT_DATA_ROOT))
    save_password: bool = False
    notes: str = ""

    @property
    def normalized_host(self) -> str:
        return self.host.replace("http://", "").replace("https://", "").strip("/")

    @property
    def crm_base_url(self) -> str:
        return f"http://{self.normalized_host}:{self.crm_port}"

    @property
    def dashboard_url(self) -> str:
        if self.dashboard_port in {80, 0}:
            return f"http://{self.normalized_host}/dashboard"
        return f"http://{self.normalized_host}:{self.dashboard_port}/dashboard"

    @property
    def pacs_base_url(self) -> str:
        return f"http://{self.normalized_host}:{self.pacs_port}"

    @property
    def socket_base_url(self) -> str:
        return f"http://{self.normalized_host}:{self.socket_port}"

    @property
    def base_urls(self) -> dict[str, str]:
        return {
            "crm_api": f"{self.crm_base_url}/api",
            "dashboard": self.dashboard_url,
            "pacs_api": f"{self.pacs_base_url}/api",
            "socket": self.socket_base_url,
        }

    def resolved_password(self, password_override: str | None = None) -> str:
        if password_override:
            return password_override
        if self.password:
            return self.password
        return os.getenv(self.password_env) or os.getenv("INO_PASS") or os.getenv("RECEPTION_CRM_PASSWORD") or ""

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["password"] = "<saved>" if self.password else ""
        data["base_urls"] = self.base_urls
        return data


@dataclass
class AppSettings:
    active_profile: str = "default"
    profiles: dict[str, ConnectionProfile] = field(default_factory=dict)

    def active(self) -> ConnectionProfile:
        if self.active_profile in self.profiles:
            return self.profiles[self.active_profile]
        if self.profiles:
            return next(iter(self.profiles.values()))
        profile = default_profile_from_env()
        self.profiles[profile.name] = profile
        self.active_profile = profile.name
        return profile

    def public_dict(self) -> dict[str, Any]:
        return {
            "settings_path": str(settings_path()),
            "active_profile": self.active_profile,
            "profiles": {name: profile.public_dict() for name, profile in self.profiles.items()},
        }


def app_config_dir() -> Path:
    root = os.getenv("APPDATA")
    if root:
        return Path(root) / APP_DIR_NAME
    return Path.home() / ".reception-crm-agent"


def settings_path() -> Path:
    return Path(os.getenv("RECEPTION_AGENT_SETTINGS") or app_config_dir() / SETTINGS_FILE_NAME)


def default_profile_from_env() -> ConnectionProfile:
    return ConnectionProfile(
        name=os.getenv("RECEPTION_PROFILE") or "default",
        center=resolve_center(),
        host=os.getenv("INO_HOST") or os.getenv("RECEPTION_CRM_HOST") or "81.16.117.196",
        crm_port=int(os.getenv("INO_CRM_PORT") or os.getenv("RECEPTION_CRM_PORT") or "8080"),
        dashboard_port=int(os.getenv("INO_DASHBOARD_PORT") or os.getenv("RECEPTION_DASHBOARD_PORT") or "80"),
        pacs_port=int(os.getenv("INO_PACS_PORT") or os.getenv("RECEPTION_PACS_PORT") or "8000"),
        socket_port=int(os.getenv("INO_SOCKET_PORT") or os.getenv("RECEPTION_SOCKET_PORT") or "50052"),
        username=os.getenv("INO_USER") or os.getenv("RECEPTION_CRM_USERNAME") or "",
        password=os.getenv("INO_PASS") or os.getenv("RECEPTION_CRM_PASSWORD") or "",
        data_root=os.getenv("RECEPTION_CRM_DATA_ROOT") or str(DEFAULT_DATA_ROOT),
        save_password=bool(os.getenv("INO_PASS") or os.getenv("RECEPTION_CRM_PASSWORD")),
    )


def load_settings(path: str | Path | None = None) -> AppSettings:
    target = Path(path) if path else settings_path()
    if not target.exists():
        profile = default_profile_from_env()
        return AppSettings(active_profile=profile.name, profiles={profile.name: profile})
    with target.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    profiles = {
        name: ConnectionProfile(**profile_raw)
        for name, profile_raw in raw.get("profiles", {}).items()
    }
    return AppSettings(active_profile=raw.get("active_profile", "default"), profiles=profiles)


def save_settings(settings: AppSettings, path: str | Path | None = None) -> Path:
    target = Path(path) if path else settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = {
        "active_profile": settings.active_profile,
        "profiles": {
            name: asdict(profile)
            for name, profile in settings.profiles.items()
        },
    }
    with target.open("w", encoding="utf-8") as handle:
        json.dump(raw, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target


def upsert_profile(profile_data: dict[str, Any]) -> AppSettings:
    settings = load_settings()
    profile = ConnectionProfile(
        name=str(profile_data.get("name") or "default"),
        center=str(profile_data.get("center") or resolve_center()),
        host=str(profile_data.get("host") or "81.16.117.196"),
        crm_port=int(profile_data.get("crm_port") or 8080),
        dashboard_port=int(profile_data.get("dashboard_port") or 80),
        pacs_port=int(profile_data.get("pacs_port") or 8000),
        socket_port=int(profile_data.get("socket_port") or 50052),
        username=str(profile_data.get("username") or ""),
        password=str(profile_data.get("password") or "") if bool(profile_data.get("save_password")) else "",
        password_env=str(profile_data.get("password_env") or "INO_PASS"),
        data_root=str(profile_data.get("data_root") or DEFAULT_DATA_ROOT),
        save_password=bool(profile_data.get("save_password")),
        notes=str(profile_data.get("notes") or ""),
    )
    settings.profiles[profile.name] = profile
    settings.active_profile = profile.name
    save_settings(settings)
    return settings
