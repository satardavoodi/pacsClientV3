"""Three isolated connection namespaces.

The app talks to three different worlds, and they must not share credentials,
ports, or state:

    receptionApi        this app  ->  the practice/reception CRM (INO)
    externalMcpClients  Claude Desktop / Cowork  ->  this app's MCP server
    mobileInternalLlm   Android EcoMind -> this app -> internal LLM -> orchestrator

Each is stored under its own key, saved independently, and projected into its
own environment variables. Saving one namespace rewrites only that namespace —
``save_section`` re-reads the file first, so two sections can never clobber each
other.

Secrets are DPAPI-encrypted at rest (``secrets.py``). They are decrypted only
when projected into ``os.environ`` for the subprocesses/threads that need them,
and never written to a log, a manifest, or an audit record.

File: %APPDATA%\\Reception CRM Agent\\connections.json
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import secrets as secret_store
from .runtime import DEFAULT_DATA_ROOT
from .settings import app_config_dir, load_settings, resolve_center

CONNECTIONS_FILE_NAME = "connections.json"

RECEPTION = "receptionApi"
EXTERNAL_MCP = "externalMcpClients"
MOBILE_LLM = "mobileInternalLlm"

SECTIONS = (RECEPTION, EXTERNAL_MCP, MOBILE_LLM)

# Which field of each section is a secret. Used for encryption on save and for
# masking on display — one list, so a new secret can't be forgotten in one place.
SECRET_FIELDS: dict[str, tuple[str, ...]] = {
    RECEPTION: ("password",),
    EXTERNAL_MCP: ("access_token",),
    MOBILE_LLM: ("device_token", "llm_api_key", "session_secret"),
}


def connections_path() -> Path:
    return Path(os.getenv("RECEPTION_CONNECTIONS_FILE") or app_config_dir() / CONNECTIONS_FILE_NAME)


# --------------------------------------------------------------------------- #
# 1. Reception / practice-management API
# --------------------------------------------------------------------------- #
@dataclass
class ReceptionApiConnection:
    """This app -> the reception software's REST API."""

    enabled: bool = True
    center: str = field(default_factory=resolve_center)
    protocol: str = "http"           # http | https
    host: str = "81.16.117.196"
    crm_port: int = 8080
    pacs_port: int = 8000
    dashboard_port: int = 80
    socket_port: int = 50052
    api_base_path: str = "/api"
    auth_method: str = "password"    # password | token
    username: str = ""
    password: str = ""               # DPAPI-encrypted at rest
    access_token: str = ""           # when auth_method == "token"
    timeout: int = 30
    data_root: str = field(default_factory=lambda: str(DEFAULT_DATA_ROOT))

    @property
    def normalized_host(self) -> str:
        return self.host.replace("http://", "").replace("https://", "").strip("/")

    @property
    def base_url(self) -> str:
        return f"{self.protocol}://{self.normalized_host}:{self.crm_port}"

    @property
    def api_url(self) -> str:
        return f"{self.base_url}{self.api_base_path}"

    def validate(self) -> list[str]:
        errors = []
        if not self.normalized_host:
            errors.append("آدرس سرور الزامی است.")
        if not 1 <= int(self.crm_port) <= 65535:
            errors.append("پورت CRM باید بین ۱ تا ۶۵۵۳۵ باشد.")
        if self.auth_method == "password" and not self.username:
            errors.append("نام کاربری الزامی است.")
        if not self.api_base_path.startswith("/"):
            errors.append("مسیر پایهٔ API باید با / شروع شود.")
        if int(self.timeout) <= 0:
            errors.append("مهلت درخواست باید بزرگ‌تر از صفر باشد.")
        return errors

    def apply_env(self) -> None:
        os.environ["INO_HOST"] = self.normalized_host
        os.environ["INO_CRM_PORT"] = str(self.crm_port)
        os.environ["INO_PACS_PORT"] = str(self.pacs_port)
        os.environ["INO_DASHBOARD_PORT"] = str(self.dashboard_port)
        os.environ["INO_SOCKET_PORT"] = str(self.socket_port)
        os.environ["RECEPTION_CENTER"] = self.center
        os.environ["RECEPTION_CRM_DATA_ROOT"] = self.data_root
        if self.username:
            os.environ["INO_USER"] = self.username
        password = secret_store.unprotect(self.password)
        if password:
            os.environ["INO_PASS"] = password


# --------------------------------------------------------------------------- #
# 2. External AI clients (MCP)
# --------------------------------------------------------------------------- #
@dataclass
class ExternalMcpConnection:
    """Claude Desktop / Cowork / other MCP clients -> this app's MCP server.

    These clients bring their own reasoning brain. This app only exposes tools;
    it does not need an LLM key for them. That is why there is none here.
    """

    transport: str = "stdio"         # stdio | http
    host: str = "127.0.0.1"
    port: int = 8790
    require_auth: bool = True
    access_token: str = ""           # DPAPI-encrypted at rest
    allow_remote: bool = False       # bind beyond loopback
    autostart: bool = False

    def validate(self) -> list[str]:
        errors = []
        if self.transport not in {"stdio", "http"}:
            errors.append("نوع انتقال نامعتبر است.")
        if self.transport == "http":
            if not 1 <= int(self.port) <= 65535:
                errors.append("پورت باید بین ۱ تا ۶۵۵۳۵ باشد.")
            if self.allow_remote and not self.require_auth:
                errors.append(
                    "دسترسی از شبکه بدون احراز هویت مجاز نیست: ابزارهای بالینی روی شبکه باز می‌شوند."
                )
            if self.require_auth and not secret_store.unprotect(self.access_token):
                errors.append("توکن دسترسی الزامی است (یا احراز هویت را خاموش کنید).")
        return errors

    @property
    def bind_host(self) -> str:
        return "0.0.0.0" if self.allow_remote else "127.0.0.1"

    @property
    def url(self) -> str:
        display = self.host if self.allow_remote else "127.0.0.1"
        return f"http://{display}:{self.port}/mcp"

    def client_config(self, project_root: str | Path) -> dict[str, Any]:
        """The snippet the user pastes into Claude Desktop / Cowork."""
        if self.transport == "http":
            entry: dict[str, Any] = {"type": "http", "url": self.url}
            if self.require_auth:
                entry["headers"] = {"Authorization": "Bearer <YOUR_TOKEN>"}
            return {"mcpServers": {"reception-crm": entry}}
        return {
            "mcpServers": {
                "reception-crm": {
                    "command": "python",
                    "args": ["-m", "reception_crm.cli", "mcp"],
                    "cwd": str(project_root),
                }
            }
        }


# --------------------------------------------------------------------------- #
# 3. Mobile app + internal LLM brain
# --------------------------------------------------------------------------- #
@dataclass
class MobileInternalLlmConnection:
    """Android EcoMind -> this app's command endpoint -> internal LLM -> orchestrator.

    The phone transcribes; it does not interpret. Interpretation happens here,
    which is why the LLM credentials live in this section and not in the MCP one.
    """

    enabled: bool = False
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 8770
    protocol: str = "http"
    allow_lan: bool = False
    device_token: str = ""           # DPAPI-encrypted — the phone's bearer token
    session_secret: str = ""         # DPAPI-encrypted — signs mobile sessions
    api_user: str = "vahid"
    api_center: str = field(default_factory=resolve_center)
    api_roles: str = "owner"

    # "company" = the Iran Nobat backend, configured entirely by the build
    # (endpoint, model, key — see llm/company_backend.py). The four fields below
    # it are therefore OPENAI-ONLY: on the company backend they are ignored, and
    # the settings screen does not show them.
    llm_backend: str = "company"     # company (Iran Nobat) | openai
    llm_model: str = "gpt-5.2"       # openai backend only
    llm_api_key: str = ""            # openai backend only; DPAPI-encrypted at rest
    llm_base_url: str = ""           # openai backend only
    llm_timeout: int = 60
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1200
    llm_proxy: str = ""

    retry_attempts: int = 2
    enable_writes: bool = False

    @property
    def gateway_url(self) -> str:
        return f"{self.protocol}://{self.gateway_host}:{self.gateway_port}"

    @property
    def bind_host(self) -> str:
        return "0.0.0.0" if self.allow_lan else "127.0.0.1"

    def validate(self) -> list[str]:
        errors = []
        if not 1 <= int(self.gateway_port) <= 65535:
            errors.append("پورت درگاه موبایل باید بین ۱ تا ۶۵۵۳۵ باشد.")
        if self.allow_lan and not secret_store.unprotect(self.device_token):
            errors.append("برای دسترسی از شبکه، توکن دستگاه الزامی است.")
        if self.llm_backend not in {"company", "openai"}:
            errors.append("بک‌اند LLM نامعتبر است.")
        # Only the user's own OpenAI account needs a key from the user. The
        # company backend carries its own, so demanding one here would block a
        # correctly configured clinic from saving.
        elif self.enabled and self.llm_backend == "openai" and not secret_store.unprotect(self.llm_api_key):
            errors.append("برای استفاده از حساب OpenAI خودتان، کلید API الزامی است.")
        if int(self.llm_timeout) <= 0:
            errors.append("مهلت LLM باید بزرگ‌تر از صفر باشد.")
        return errors

    @property
    def uses_company_backend(self) -> bool:
        return self.llm_backend != "openai"

    def apply_env(self) -> None:
        os.environ["RECEPTION_LLM_BACKEND"] = self.llm_backend
        # A model name saved from an earlier build must not reach the company
        # backend, whose model is fixed at build time. Exporting it would let a
        # stale settings file name a retired model and break the assistant.
        os.environ["RECEPTION_LLM_MODEL"] = "" if self.uses_company_backend else self.llm_model
        os.environ["RECEPTION_LLM_TIMEOUT"] = str(self.llm_timeout)
        os.environ["RECEPTION_LLM_TEMPERATURE"] = str(self.llm_temperature)
        os.environ["RECEPTION_LLM_MAX_TOKENS"] = str(self.llm_max_tokens)
        os.environ["RECEPTION_LLM_PROXY"] = self.llm_proxy
        os.environ["RECEPTION_HTTP_API_USER"] = self.api_user
        os.environ["RECEPTION_HTTP_API_CENTER"] = self.api_center
        os.environ["RECEPTION_HTTP_API_ROLES"] = self.api_roles
        os.environ["RECEPTION_ENABLE_WRITES"] = "true" if self.enable_writes else "false"

        # ``llm_api_key`` is the user's OWN OpenAI key and nothing else. The
        # company backend supplies its own key from the build, so this value must
        # never be exported as RECEPTION_LLM_API_KEY — a key left over from a
        # spell on the OpenAI backend would otherwise override the bundled one
        # and every request would fail with an authentication error.
        key = secret_store.unprotect(self.llm_api_key)
        if self.uses_company_backend:
            os.environ.pop("RECEPTION_OPENAI_API_KEY", None)
            os.environ.pop("RECEPTION_OPENAI_BASE_URL", None)
        elif key:
            os.environ["RECEPTION_OPENAI_API_KEY"] = key
            if self.llm_base_url:
                os.environ["RECEPTION_OPENAI_BASE_URL"] = self.llm_base_url

        token = secret_store.unprotect(self.device_token)
        if token:
            os.environ["RECEPTION_HTTP_API_TOKEN"] = token
        session = secret_store.unprotect(self.session_secret)
        if session:
            os.environ["RECEPTION_SESSION_SECRET"] = session


# --------------------------------------------------------------------------- #
# store
# --------------------------------------------------------------------------- #
_TYPES: dict[str, type] = {
    RECEPTION: ReceptionApiConnection,
    EXTERNAL_MCP: ExternalMcpConnection,
    MOBILE_LLM: MobileInternalLlmConnection,
}


@dataclass
class Connections:
    receptionApi: ReceptionApiConnection = field(default_factory=ReceptionApiConnection)
    externalMcpClients: ExternalMcpConnection = field(default_factory=ExternalMcpConnection)
    mobileInternalLlm: MobileInternalLlmConnection = field(default_factory=MobileInternalLlmConnection)

    def section(self, name: str):
        return getattr(self, name)

    def apply_env(self) -> None:
        """Project every section into the environment (startup)."""
        self.receptionApi.apply_env()
        self.mobileInternalLlm.apply_env()

    def public_dict(self) -> dict[str, Any]:
        """Safe for display and logs: secrets are masked, never included."""
        out: dict[str, Any] = {}
        for name in SECTIONS:
            data = asdict(self.section(name))
            for secret_field in SECRET_FIELDS[name]:
                data[secret_field] = secret_store.mask(data.get(secret_field))
            out[name] = data
        return out


def load_connections(path: str | Path | None = None) -> Connections:
    target = Path(path) if path else connections_path()
    if not target.exists():
        return _migrate_from_legacy_settings()

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Connections()

    return Connections(**{name: _build(name, raw.get(name) or {}) for name in SECTIONS})


def save_section(name: str, values: dict[str, Any], path: str | Path | None = None) -> Connections:
    """Write ONE namespace. The other two are re-read from disk and preserved.

    This is what makes the sections isolated: there is no code path where saving
    the mobile section can touch the reception credentials.
    """
    if name not in SECTIONS:
        raise ValueError(f"Unknown connection section: {name}")

    target = Path(path) if path else connections_path()
    current = load_connections(target)

    setattr(current, name, _build(name, values, previous=current.section(name)))

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {section: asdict(current.section(section)) for section in SECTIONS}
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)  # atomic: a crash mid-write cannot truncate the file
    return current


def _build(name: str, values: dict[str, Any], previous: Any = None):
    """Construct a section, encrypting secrets and keeping unchanged ones."""
    cls = _TYPES[name]
    known = set(getattr(cls, "__dataclass_fields__", {}))
    data = {key: value for key, value in (values or {}).items() if key in known}

    for secret_field in SECRET_FIELDS[name]:
        incoming = data.get(secret_field, None)

        if incoming is None:
            # Field not supplied: keep whatever was already stored.
            if previous is not None:
                data[secret_field] = getattr(previous, secret_field, "")
            continue

        incoming = str(incoming)
        if incoming == "":
            # Explicitly cleared.
            data[secret_field] = ""
        elif secret_store.is_protected(incoming):
            data[secret_field] = incoming
        elif incoming == secret_store.mask(incoming):  # UI echoed the mask back
            data[secret_field] = getattr(previous, secret_field, "") if previous else ""
        else:
            try:
                data[secret_field] = secret_store.protect(incoming)
            except RuntimeError:
                # No DPAPI (non-Windows): refuse to persist plaintext.
                data[secret_field] = ""

    return cls(**data)


def _migrate_from_legacy_settings() -> Connections:
    """First run: carry the old single ConnectionProfile into receptionApi.

    The legacy settings.json is left untouched — the old CLI/gateway code still
    reads it, and this is not the moment to break them.
    """
    connections = Connections()
    try:
        profile = load_settings().active()
    except Exception:  # noqa: BLE001 - a broken legacy file must not block startup
        return connections

    reception = connections.receptionApi
    reception.center = profile.center or reception.center
    reception.host = profile.host or reception.host
    reception.crm_port = int(profile.crm_port or reception.crm_port)
    reception.pacs_port = int(profile.pacs_port or reception.pacs_port)
    reception.dashboard_port = int(profile.dashboard_port or reception.dashboard_port)
    reception.socket_port = int(profile.socket_port or reception.socket_port)
    reception.username = profile.username or ""
    reception.data_root = profile.data_root or reception.data_root

    password = profile.resolved_password()
    if password and secret_store.is_available():
        try:
            reception.password = secret_store.protect(password)
        except RuntimeError:
            reception.password = ""
    return connections
