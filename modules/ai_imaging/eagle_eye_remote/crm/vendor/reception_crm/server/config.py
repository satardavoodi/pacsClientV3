"""Server configuration: file on disk, overridden by environment.

Both connection modes the deployment requires are served by a single listener:

* ``localhost`` / ``127.0.0.1`` — local API callers on the server machine
* the center's static public IP, via the port forwarded on the modem

Binding to ``0.0.0.0`` satisfies both at once; there is no need for two
listeners or two ports. ``bind`` selects between loopback-only ("local") and
all interfaces ("all").

Precedence, highest first:
  1. environment variables (so an operator can override without editing files)
  2. ``server.json`` in ``runtime.config_root()``
  3. the defaults below
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..runtime import config_root, data_root

CONFIG_FILENAME = "server.json"

DEFAULT_PORT = 8770
LOOPBACK = "127.0.0.1"
ALL_INTERFACES = "0.0.0.0"

DEFAULT_RECEPTION_PORT = 8080

#: The vendor's usual on-disk layout. A per-site fact with a sensible default,
#: not a product constant -- see ReceptionConfig.file_roots.
DEFAULT_FILE_ROOTS: tuple[str, ...] = (
    r"D:\api\images\ReceptionAttachments",
    r"D:\Program Files\data\captures",
    r"D:\Program Files\AI_PACS_SERVER\data\dicom_data",
)
DEFAULT_LLM_PROVIDER = "company"
#: Empty on purpose: "whatever this build ships", resolved by
#: `llm/config.model()`. Naming a model here duplicated the one in
#: `company_backend` and the two then drifted -- an operator reading
#: `describe` saw this value while the server called that one.
DEFAULT_LLM_MODEL = ""
DEFAULT_LLM_TIMEOUT = 60
DEFAULT_LLM_TEMPERATURE = 0.0
DEFAULT_LLM_MAX_TOKENS = 1200


@dataclass
class LlmConfig:
    """Where the analysis brain lives and how it is called.

    The key lives HERE, on the machine, and never in a client binary — that is
    the whole point of the mobile app sending text rather than calling an LLM
    itself. ``provider`` selects between the company (GapGPT-compatible)
    endpoint and OpenAI; ``base_url`` is only consulted for the latter.
    """

    provider: str = DEFAULT_LLM_PROVIDER  # "company" | "openai"
    api_key: str = ""
    base_url: str = ""  # openai only; blank uses the provider default
    model: str = DEFAULT_LLM_MODEL
    timeout: int = DEFAULT_LLM_TIMEOUT
    temperature: float = DEFAULT_LLM_TEMPERATURE
    max_tokens: int = DEFAULT_LLM_MAX_TOKENS
    proxy: str = ""  # blank means an EXPLICIT direct connection, not "inherit"

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def effective_model(self) -> str:
        """The model that will actually be called.

        `self.model` is what the config FILE says, which is not the same thing:
        blank means "this build's default". Reporting the file's value made
        `describe` state a model the server was not calling the moment the two
        differed, which is the kind of true-but-wrong line somebody debugs for
        an hour.
        """
        try:
            from ..llm import config as llm_config

            return llm_config.model()
        except Exception:  # noqa: BLE001 - diagnostics must not raise
            return self.model

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.effective_model,
            "model_configured": self.model or "(build default)",
            "base_url": self.base_url,
            "timeout": self.timeout,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "proxy_set": bool(self.proxy),
            "api_key_set": bool(self.api_key),
        }


@dataclass
class ReceptionConfig:
    """How to reach the reception software — which is on THIS machine.

    There is deliberately no ``host`` field. This agent is installed on the
    reception server, so the address is a deployment fact rather than a user
    preference, and it is resolved at run time by ``reception_crm.local_host``
    (which also documents why it cannot simply be ``127.0.0.1``). Exposing a
    host here would let one clinic's install be pointed at another clinic's
    reception server, which is exactly what must not be possible.
    """

    port: int = DEFAULT_RECEPTION_PORT
    username: str = ""
    password: str = ""
    #: Folders on THIS machine where the reception software keeps the files it
    #: records in the database. The integrity check opens a stored path only if
    #: it sits under one of these -- a path out of the database is a stored
    #: string like any other, and without an allow-list "check the file exists"
    #: becomes "open whatever the database says".
    #:
    #: It is configurable because the layout is a per-site fact, not a product
    #: constant. The defaults are this vendor's usual layout; a site that keeps
    #: its images elsewhere sets its own and `integrity.broken-files` reports
    #: `pathsOutsideKnownRoots` so a wrong list is visible rather than silent.
    file_roots: tuple[str, ...] = DEFAULT_FILE_ROOTS

    @property
    def configured(self) -> bool:
        return bool(self.username and self.password)

    def public_dict(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "username": self.username,
            "password_set": bool(self.password),
            "host": "resolved locally on this machine",
            "file_roots": list(self.file_roots),
        }


@dataclass
class ServerConfig:
    """Everything the server process needs to start."""

    bind: str = "local"  # "local" | "all"
    port: int = DEFAULT_PORT
    center: str = ""
    data_root: Path = field(default_factory=data_root)

    # The two outward connections, both owned by this file so that one
    # installer-written config governs the whole deployment.
    llm: LlmConfig = field(default_factory=LlmConfig)
    reception: ReceptionConfig = field(default_factory=ReceptionConfig)

    # Auth. The session secret keeps per-user sessions valid across restarts;
    # without it every service restart silently logs every phone out.
    session_secret: str = ""
    shared_token: str = ""

    # TLS is off by default to match the existing PACS/Reception channels.
    # Populating these two fields is the only change needed to turn it on.
    tls_certfile: str = ""
    tls_keyfile: str = ""

    log_level: str = "INFO"
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5

    @property
    def host(self) -> str:
        return ALL_INTERFACES if self.bind == "all" else LOOPBACK

    @property
    def tls_enabled(self) -> bool:
        return bool(self.tls_certfile)

    @property
    def scheme(self) -> str:
        return "https" if self.tls_enabled else "http"

    def public_dict(self) -> dict[str, Any]:
        """Loggable view. Never includes the secret or the token."""
        return {
            "bind": self.bind,
            "host": self.host,
            "port": self.port,
            "center": self.center,
            "scheme": self.scheme,
            "tls_enabled": self.tls_enabled,
            "data_root": str(self.data_root),
            "log_level": self.log_level,
            "session_secret_set": bool(self.session_secret),
            "shared_token_set": bool(self.shared_token),
            "llm": self.llm.public_dict(),
            "reception": self.reception.public_dict(),
        }

    def validate(self) -> list[str]:
        """Return blocking problems. Empty list means safe to start."""
        problems: list[str] = []

        if self.bind not in {"local", "all"}:
            problems.append(f"bind must be 'local' or 'all', got {self.bind!r}")

        if not (1 <= self.port <= 65535):
            problems.append(f"port out of range: {self.port}")

        # This mirrors the guard already in the HTTP adapter. Exposing the
        # endpoint beyond loopback with no credential at all would let anyone
        # who can reach the port query patient data.
        if self.bind == "all" and not (self.shared_token or self.session_secret):
            problems.append(
                "bind='all' exposes the port beyond this machine; set session_secret "
                "(preferred) or shared_token first"
            )

        if self.tls_certfile and not Path(self.tls_certfile).exists():
            problems.append(f"tls_certfile not found: {self.tls_certfile}")

        if self.tls_keyfile and not Path(self.tls_keyfile).exists():
            problems.append(f"tls_keyfile not found: {self.tls_keyfile}")

        if self.llm.provider not in {"company", "openai"}:
            problems.append(f"llm.provider must be 'company' or 'openai', got {self.llm.provider!r}")

        if not (1 <= self.reception.port <= 65535):
            problems.append(f"reception.port out of range: {self.reception.port}")

        return problems

    def warnings(self) -> list[str]:
        """Non-blocking concerns worth putting in the log on every start."""
        notes: list[str] = []

        if not self.session_secret:
            notes.append(
                "session_secret is empty: mobile sessions will not survive a service restart"
            )

        if self.bind == "all" and not self.tls_enabled:
            notes.append(
                "bind='all' without TLS: requests and bearer tokens travel in clear text. "
                "This matches the existing PACS/Reception channels; set tls_certfile to change it."
            )

        if not Path(self.data_root).exists():
            notes.append(f"data_root does not exist yet: {self.data_root}")

        notes.extend(self._center_notes())
        notes.extend(self._center_catalog_notes())
        notes.extend(self._model_notes())

        # These two are warnings rather than problems on purpose: the server
        # must still start and answer /api/health so an operator can see WHY it
        # is not useful yet, instead of a service that refuses to run.
        if not self.llm.configured:
            notes.append(
                "llm.api_key is empty: /api/agent/command will return LLM_NOT_CONFIGURED "
                "and the mobile app can run no commands"
            )

        if not self.reception.configured:
            notes.append(
                "reception.username / reception.password are empty: no tool can read "
                "practice data and no user can sign in"
            )

        return notes

    def _center_catalog_notes(self) -> list[str]:
        """Make an absent or foreign service catalogue visible on startup."""
        path = config_root() / "center_config.json"
        if not path.exists():
            # Source development keeps its measured map inside the package;
            # frozen installs must always use the ProgramData map generated on
            # that machine. Accept the source map only when its centre matches.
            from .. import runtime
            from ..lexicon.center import BUNDLED_CENTER_CONFIG_PATH

            if not runtime.is_frozen() and BUNDLED_CENTER_CONFIG_PATH.exists():
                path = BUNDLED_CENTER_CONFIG_PATH
            else:
                return [
                    f"center catalogue is missing at {path}: run "
                    "ReceptionCrmServer.exe bootstrap-center before trusting service searches"
                ]
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return [f"center catalogue cannot be read ({type(exc).__name__}): {path}"]
        if not isinstance(payload, dict):
            return [f"center catalogue is not a JSON object: {path}"]
        catalog_center = str(payload.get("center") or "").strip()
        if self.center and catalog_center.casefold() != self.center.casefold():
            return [
                f"center catalogue belongs to {catalog_center or 'unnamed/legacy'!r}, "
                f"not configured centre {self.center!r}: run bootstrap-center"
            ]
        return []

    def _model_notes(self) -> list[str]:
        """Say out loud when the config file is overriding the build's model.

        This is the guard that makes the override safe. The override was once
        forbidden outright, on the reasoning that a stale settings file naming a
        retired model would break the assistant with nothing to explain why —
        a real risk, and the reason this note exists rather than nothing.

        Never raises: it runs on the service start path.
        """
        configured = (self.llm.model or "").strip()
        if not configured:
            return []
        try:
            from ..llm import company_backend

            build_model = company_backend.MODEL
        except Exception:  # noqa: BLE001
            return []
        if configured == build_model:
            return []
        return [
            f"llm.model in the configuration is overriding this build's model: "
            f"using {configured!r} instead of {build_model!r}. Clear it to go back "
            f"to the model this build was tested with."
        ]

    def _center_notes(self) -> list[str]:
        """Is the configured centre one the roles policy actually knows?

        Found on the first clean-install rehearsal. With no centre configured
        the server started, `validate()` returned no problems and `/api/health`
        reported nothing wrong -- and every single sign-in was then refused
        deep inside the policy with "user is not allowed for this center",
        which names neither the centre that was configured nor the ones that
        would work. "No problems" was a true statement answering a different
        question.

        A typo is the same failure: RAZ instead of RAZI passes every check
        here and denies every user there. So compare against the policy rather
        than merely testing for emptiness, and name what the policy expects.

        Deliberately a warning, not a blocking problem, for the reason given
        above: the operator has to be able to start the service and read
        /api/health to find out what is wrong with it.

        Never raises. This runs on the service start path, and a malformed or
        missing roles.json must not stop the server from coming up and saying
        so.
        """
        notes: list[str] = []
        if not self.center:
            notes.append(
                "center is empty: the service starts, but every sign-in is refused "
                "because no user in roles.json matches an unnamed center. Set "
                '"center" in server.json to the name used in roles.json.'
            )
            return notes

        try:
            from ..permissions import load_permissions

            policy = load_permissions()
        except FileNotFoundError:
            notes.append(
                "no roles.json found: every sign-in will be refused. Copy "
                "roles.example.json next to server.json and set its center and users."
            )
            return notes
        except Exception as error:  # malformed JSON, unreadable file, ...
            notes.append(f"roles policy could not be read ({error}); sign-in may fail")
            return notes

        known = sorted(
            {
                str(record.get("center"))
                for record in policy.users.values()
                if isinstance(record, dict) and record.get("center")
            }
        )
        if known and self.center not in known:
            notes.append(
                f"center {self.center!r} matches no user in {policy.path}: every "
                f"sign-in will be refused. Centers named there: {', '.join(known)}."
            )
        return notes


def config_path() -> Path:
    return config_root() / CONFIG_FILENAME


def _read_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        # utf-8-sig, not utf-8: PowerShell 5.1's `Set-Content -Encoding UTF8`
        # (used by scripts/set_shared_token.ps1) writes a BOM. Strict utf-8
        # then raises JSONDecodeError, this function silently returns {}, and
        # the service starts on defaults -- bind=local, no session_secret --
        # which looks like "the server just stopped answering on the LAN".
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        # A malformed config must not stop the service from starting on
        # defaults; the runner logs this separately.
        return {}


def _env_int(name: str, fallback: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return fallback
    try:
        return int(raw)
    except ValueError:
        return fallback


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    """One nested object from server.json, tolerant of a missing or wrong type.

    A config written by an OLDER installer has no ``llm`` / ``reception`` block
    at all — the installer never rewrites an existing server.json — so every
    field below must survive the section being absent.
    """
    value = raw.get(name)
    return value if isinstance(value, dict) else {}


def _load_llm(raw: dict[str, Any]) -> LlmConfig:
    section = _section(raw, "llm")
    return LlmConfig(
        provider=str(
            os.getenv("RECEPTION_LLM_BACKEND") or section.get("provider") or DEFAULT_LLM_PROVIDER
        ).strip().lower(),
        api_key=os.getenv("RECEPTION_LLM_API_KEY")
        or os.getenv("RECEPTION_OPENAI_API_KEY")
        or str(section.get("api_key") or ""),
        base_url=os.getenv("RECEPTION_OPENAI_BASE_URL") or str(section.get("base_url") or ""),
        model=os.getenv("RECEPTION_LLM_MODEL") or str(section.get("model") or DEFAULT_LLM_MODEL),
        timeout=_env_int("RECEPTION_LLM_TIMEOUT", _as_int(section.get("timeout"), DEFAULT_LLM_TIMEOUT)),
        temperature=_as_float(
            os.getenv("RECEPTION_LLM_TEMPERATURE") or section.get("temperature"),
            DEFAULT_LLM_TEMPERATURE,
        ),
        max_tokens=_env_int(
            "RECEPTION_LLM_MAX_TOKENS", _as_int(section.get("max_tokens"), DEFAULT_LLM_MAX_TOKENS)
        ),
        proxy=os.getenv("RECEPTION_LLM_PROXY") or str(section.get("proxy") or ""),
    )


def _load_reception(raw: dict[str, Any]) -> ReceptionConfig:
    section = _section(raw, "reception")
    return ReceptionConfig(
        port=_env_int(
            "INO_CRM_PORT", _as_int(section.get("port"), DEFAULT_RECEPTION_PORT)
        ),
        username=os.getenv("INO_USER") or str(section.get("username") or ""),
        password=os.getenv("INO_PASS") or str(section.get("password") or ""),
        file_roots=_file_roots(section.get("file_roots")),
    )


def _file_roots(value: Any) -> tuple[str, ...]:
    """Read the site's storage roots, falling back to the vendor's usual layout.

    An empty or malformed list falls back rather than yielding an empty
    allow-list: an empty list would silently disable the file check entirely,
    which looks exactly like "no broken links" and is the wrong failure.
    """
    env = os.getenv("RECEPTION_FILE_ROOTS")
    if env:
        value = [part for part in env.split(os.pathsep) if part.strip()]
    if not isinstance(value, (list, tuple)):
        return DEFAULT_FILE_ROOTS
    roots = tuple(str(v).strip() for v in value if str(v).strip())
    return roots or DEFAULT_FILE_ROOTS


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def load_server_config(path: Path | None = None) -> ServerConfig:
    """Build the effective configuration from file plus environment."""
    source = path or config_path()
    raw = _read_file(source)

    bind = os.getenv("RECEPTION_SERVER_BIND") or raw.get("bind") or "local"
    port = _env_int("RECEPTION_SERVER_PORT", int(raw.get("port") or DEFAULT_PORT))

    configured_root = os.getenv("RECEPTION_CRM_DATA_ROOT") or raw.get("data_root")

    config = ServerConfig(
        bind=str(bind).strip().lower(),
        port=port,
        center=os.getenv("RECEPTION_HTTP_API_CENTER") or raw.get("center") or "",
        data_root=Path(configured_root) if configured_root else data_root(),
        session_secret=os.getenv("RECEPTION_SESSION_SECRET") or raw.get("session_secret") or "",
        shared_token=os.getenv("RECEPTION_HTTP_API_TOKEN") or raw.get("shared_token") or "",
        tls_certfile=os.getenv("RECEPTION_TLS_CERTFILE") or raw.get("tls_certfile") or "",
        tls_keyfile=os.getenv("RECEPTION_TLS_KEYFILE") or raw.get("tls_keyfile") or "",
        log_level=(os.getenv("RECEPTION_LOG_LEVEL") or raw.get("log_level") or "INFO").upper(),
        log_max_bytes=int(raw.get("log_max_bytes") or 5 * 1024 * 1024),
        log_backup_count=int(raw.get("log_backup_count") or 5),
        llm=_load_llm(raw),
        reception=_load_reception(raw),
    )

    return config


def apply_to_environment(config: ServerConfig) -> None:
    """Publish config into the environment the existing adapter already reads.

    The HTTP adapter and the identity layer were written against environment
    variables. Rather than rewrite those call sites (and risk changing audited
    security behaviour), the server publishes its resolved configuration into
    the same variables before starting.
    """
    if config.session_secret:
        os.environ["RECEPTION_SESSION_SECRET"] = config.session_secret
    if config.shared_token:
        os.environ["RECEPTION_HTTP_API_TOKEN"] = config.shared_token
    if config.center:
        os.environ["RECEPTION_HTTP_API_CENTER"] = config.center
    os.environ["RECEPTION_CRM_DATA_ROOT"] = str(config.data_root)
    # Generated per installation by ``bootstrap-center``. The frozen bundle may
    # carry a same-centre migration seed, but it is never runtime authority.
    generated_center_path = config_root() / "center_config.json"
    from ..runtime import is_frozen

    if generated_center_path.exists() or is_frozen():
        os.environ["RECEPTION_CENTER_CONFIG_PATH"] = str(generated_center_path)
    else:
        os.environ.pop("RECEPTION_CENTER_CONFIG_PATH", None)
    # The resolver is cached because every agent request uses it. Configuration
    # is applied once on process start, so this is the one correct place to
    # discard any seed map imported before the runtime path was known.
    from ..lexicon import center as center_lexicon

    center_lexicon.reset_cache()

    # ---- LLM -------------------------------------------------------------
    # llm/config.py reads these names. Publishing them here is what lets the
    # installer-written server.json govern the brain without every call site
    # learning about ServerConfig.
    llm = config.llm
    os.environ["RECEPTION_LLM_BACKEND"] = llm.provider
    os.environ["RECEPTION_LLM_MODEL"] = llm.model
    os.environ["RECEPTION_LLM_TIMEOUT"] = str(llm.timeout)
    os.environ["RECEPTION_LLM_TEMPERATURE"] = str(llm.temperature)
    os.environ["RECEPTION_LLM_MAX_TOKENS"] = str(llm.max_tokens)
    # Set even when empty: an empty RECEPTION_LLM_PROXY means an EXPLICIT direct
    # connection. Leaving it unset would let a machine-level HTTP_PROXY silently
    # capture the LLM traffic.
    os.environ["RECEPTION_LLM_PROXY"] = llm.proxy
    if llm.api_key:
        if llm.provider == "openai":
            os.environ["RECEPTION_OPENAI_API_KEY"] = llm.api_key
            if llm.base_url:
                os.environ["RECEPTION_OPENAI_BASE_URL"] = llm.base_url
        else:
            os.environ["RECEPTION_LLM_API_KEY"] = llm.api_key

    # ---- Reception software (on THIS machine) ----------------------------
    # The host is resolved, never configured. See reception_crm/local_host.py
    # for why loopback is not usable against the vendor's practice API.
    from ..local_host import resolve_reception_host

    reception = config.reception
    os.environ["INO_HOST"] = resolve_reception_host(reception.port)
    os.environ["INO_CRM_PORT"] = str(reception.port)
    if reception.username:
        os.environ["INO_USER"] = reception.username
    if reception.password:
        os.environ["INO_PASS"] = reception.password
    # local/integrity.py reads this rather than importing the config, so the
    # file-system allow-list follows the same publish-to-environment pattern as
    # everything else and stays testable without a config file.
    os.environ["RECEPTION_FILE_ROOTS"] = os.pathsep.join(reception.file_roots)


def write_default_config(path: Path | None = None, **overrides: Any) -> Path:
    """Write a starter ``server.json``. Used by the installer, never overwrites."""
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        return target

    template: dict[str, Any] = {
        "bind": "local",
        "port": DEFAULT_PORT,
        "center": "",
        "data_root": str(data_root()),
        "session_secret": "",
        "shared_token": "",
        "tls_certfile": "",
        "tls_keyfile": "",
        "log_level": "INFO",
        "llm": {
            "provider": DEFAULT_LLM_PROVIDER,
            "api_key": "",
            "base_url": "",
            "model": DEFAULT_LLM_MODEL,
            "timeout": DEFAULT_LLM_TIMEOUT,
            "temperature": DEFAULT_LLM_TEMPERATURE,
            "max_tokens": DEFAULT_LLM_MAX_TOKENS,
            "proxy": "",
        },
        # No host here, deliberately: this agent runs ON the reception server
        # and resolves the address itself (reception_crm/local_host.py).
        "reception": {
            "port": DEFAULT_RECEPTION_PORT,
            "username": "",
            "password": "",
        },
    }
    template.update(overrides)

    with target.open("w", encoding="utf-8") as handle:
        json.dump(template, handle, indent=2, ensure_ascii=False)

    return target
