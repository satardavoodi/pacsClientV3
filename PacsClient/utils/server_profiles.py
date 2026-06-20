"""
server_profiles.py — canonical multi-server *profile* model.
============================================================

A doctor who works across several imaging centers (e.g. **Razi**, **Mehr**)
needs to define one *profile* per center and switch between them.  A profile
owns **everything** that is center-specific:

* main host + **socket port** (the real app/login/download port, was the global
  ``socket_config.json`` ``socket_port``) + **DICOM port** (C-ECHO/C-MOVE, was the
  ``servers.json`` ``port``) + AE title + poor-connectivity flag,
* optional per-center **module endpoints** (AI breast/boneage/segmentation,
  reception API, mammography, bonj, …),
* a stable **id** used as the per-server data-namespace key so two centers that
  share a PatientID / StudyInstanceUID never collide on disk or in the DB.

Design rules
------------
* **Pure & stdlib-only** — no Qt / PySide6 / pydicom / numpy imports, so it can be
  unit-tested in isolation and imported anywhere (login screen, settings, data
  paths, socket layer) without pulling a heavy chain.
* **Inert by default** — this module is the single source of truth, but the
  *behavioral* consumers (data-root namespacing, socket routing, login dropdown)
  are gated behind :func:`server_profiles_enabled` so introducing this file does
  not change any current behavior until each consumer is wired and validated.
* **Backward compatible** — when ``config/server_profiles.json`` is absent it is
  migrated from the existing ``servers.json`` + ``socket_config.json`` +
  ``servers_address.json`` so single-server users are unchanged.

Nothing in this module raises on bad input — callers get safe defaults.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# ── Constants ────────────────────────────────────────────────────────────────
SCHEMA_VERSION = 1
PROFILES_FILENAME = "server_profiles.json"

#: The socket-protocol port the live app actually uses (login, patient list,
#: thumbnails, downloads).  Per-profile now, but this is the historical default.
DEFAULT_SOCKET_PORT = 50052
#: The DICOM (DIMSE) port — C-ECHO/C-MOVE only.  Never used by the socket path.
DEFAULT_DICOM_PORT = 104
DEFAULT_AE_TITLE = "aipacs"

#: Behavioral feature flag.  Until consumers are wired + validated this stays
#: False so the legacy single-server behavior is byte-identical.  Set
#: ``AIPACS_SERVER_PROFILES=1`` to opt in.
_ENV_FLAG = "AIPACS_SERVER_PROFILES"
#: Test/override hook: absolute path to the profiles JSON file.
_ENV_PROFILES_PATH = "AIPACS_SERVER_PROFILES_PATH"
#: Test/override hook: directory that holds the config JSONs (profiles + legacy).
_ENV_CONFIG_DIR = "AIPACS_CONFIG_DIR"

#: The well-known per-profile module-endpoint slots.  A ``None`` value means
#: "not configured for this center" → the consumer falls back to the global
#: value (today) and the UI shows the slot as unavailable.
MODULE_ENDPOINT_KEYS = (
    "ai_breast",
    "ai_boneage",
    "ai_segmentation",
    "reception_api",
    "mammography",
    "bonj",
)

_lock = threading.RLock()


# ── Truthiness helper (shared env semantics) ────────────────────────────────
def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def server_profiles_enabled() -> bool:
    """Whether *behavioral* multi-server consumers should be active.

    Precedence:
      1. env ``AIPACS_SERVER_PROFILES`` (1/0) — wins, for dev/CI and kill-switch;
      2. the persisted top-level ``"enabled"`` flag in ``server_profiles.json``
         (so the user can turn the feature on from config / a Settings checkbox
         without setting an env var).

    Default False — introducing this module changes nothing until the user opts
    in, so the legacy single-server behavior stays byte-identical.
    """
    if os.environ.get(_ENV_FLAG) is not None:
        return _env_truthy(_ENV_FLAG, False)
    try:
        return bool(load_profiles_document(migrate_if_missing=False).get("enabled", False))
    except Exception:
        return False


# ── The profile model ────────────────────────────────────────────────────────
@dataclass
class ServerProfile:
    """One imaging center / server environment."""

    id: str
    display_name: str
    host: str
    socket_port: int = DEFAULT_SOCKET_PORT
    dicom_port: int = DEFAULT_DICOM_PORT
    ae_title: str = DEFAULT_AE_TITLE
    poor_connectivity: bool = False
    enabled: bool = True
    server_type: str = "ai_pacs"
    modules: dict[str, Optional[str]] = field(default_factory=dict)
    status: dict[str, Any] = field(
        default_factory=lambda: {"last_checked": None, "reachable": None}
    )

    # -- serialization -------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Always present the full module-slot set so the UI/consumers see every
        # known slot (missing → None = "not configured").
        modules = dict(data.get("modules") or {})
        for key in MODULE_ENDPOINT_KEYS:
            modules.setdefault(key, None)
        data["modules"] = modules
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ServerProfile":
        raw = dict(raw or {})
        host = str(raw.get("host", "")).strip()
        explicit_id = str(raw.get("id") or "").strip()
        name = str(raw.get("display_name") or raw.get("name") or "").strip()
        # An explicit id is trusted verbatim (the author chose it); a *derived*
        # id is slugified so it is a safe namespace key even from a hand-edited
        # file — matching build_profiles_from_legacy().
        pid = explicit_id or data_segment(name or host or "server")
        display = name or explicit_id or host or pid
        modules_in = raw.get("modules") if isinstance(raw.get("modules"), dict) else {}
        modules: dict[str, Optional[str]] = {}
        for key in MODULE_ENDPOINT_KEYS:
            val = modules_in.get(key)
            modules[key] = str(val).strip() if isinstance(val, str) and val.strip() else None
        # keep any extra custom module keys the user added
        for key, val in (modules_in or {}).items():
            if key not in modules:
                modules[key] = str(val).strip() if isinstance(val, str) and val.strip() else None
        status = raw.get("status") if isinstance(raw.get("status"), dict) else {}
        return cls(
            id=pid,
            display_name=display or pid,
            host=host,
            socket_port=_coerce_int(raw.get("socket_port"), DEFAULT_SOCKET_PORT),
            dicom_port=_coerce_int(raw.get("dicom_port", raw.get("port")), DEFAULT_DICOM_PORT),
            ae_title=str(raw.get("ae_title") or DEFAULT_AE_TITLE).strip() or DEFAULT_AE_TITLE,
            poor_connectivity=bool(raw.get("poor_connectivity", False)),
            enabled=bool(raw.get("enabled", True)),
            server_type=str(raw.get("server_type") or "ai_pacs").strip() or "ai_pacs",
            modules=modules,
            status={"last_checked": status.get("last_checked"), "reachable": status.get("reachable")},
        )

    # -- convenience ---------------------------------------------------------
    def socket_target(self) -> tuple[str, int]:
        """``(host, socket_port)`` for the live socket layer."""
        return self.host, int(self.socket_port)

    def module_endpoint(self, name: str) -> Optional[str]:
        """Per-profile endpoint for *name*, or ``None`` if not configured."""
        val = (self.modules or {}).get(name)
        return val if isinstance(val, str) and val.strip() else None

    def data_segment(self) -> str:
        """Filesystem-safe per-server namespace key (for data separation)."""
        return data_segment(self.id)


# ── small pure helpers ───────────────────────────────────────────────────────
def _coerce_int(value: Any, default: int) -> int:
    try:
        if value is None or value == "":
            return int(default)
        return int(str(value).strip())
    except (TypeError, ValueError):
        return int(default)


def data_segment(profile_id: str) -> str:
    """Return a stable, filesystem-safe folder name for *profile_id*.

    Used to namespace per-server data (database, dicom, thumbnails, attachments)
    so the same PatientID / StudyInstanceUID from two centers never collide.
    """
    raw = str(profile_id or "").strip()
    if not raw:
        return "default"
    # keep it readable but safe across Windows/Posix
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    if not slug:
        slug = "srv_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    # guard against absurdly long / reserved names
    return slug[:64]


# ── config-path resolution (lazy; avoids the heavy import chain in tests) ────
def _config_dir() -> Path:
    override = os.environ.get(_ENV_CONFIG_DIR)
    if override:
        return Path(override)
    path_override = os.environ.get(_ENV_PROFILES_PATH)
    if path_override:
        return Path(path_override).parent
    # Resolve the app config dir WITHOUT importing PacsClient.utils.config:
    # data_paths.py imports THIS module at startup and config.py imports
    # data_paths.py, so importing config here would be circular. Mirror
    # config.py's own logic using the leaf aipacs_runtime / _project_root
    # modules (which have no cycle with data_paths).
    try:  # pragma: no cover - exercised only in the full app
        import sys as _sys
        from aipacs_runtime import roaming_config_root, seed_user_config_defaults
        from _project_root import PROJECT_ROOT  # type: ignore

        if getattr(_sys, "frozen", False):
            seed_user_config_defaults()
            return Path(roaming_config_root())
        return Path(PROJECT_ROOT) / "config"
    except Exception:
        return Path.cwd() / "config"


def profiles_config_path() -> Path:
    override = os.environ.get(_ENV_PROFILES_PATH)
    if override:
        return Path(override)
    return _config_dir() / PROFILES_FILENAME


# ── legacy migration (pure builder + filesystem reader) ─────────────────────
def build_profiles_from_legacy(
    servers: list[dict[str, Any]] | None,
    socket_cfg: dict[str, Any] | None,
    ai_services: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a profiles *document* from the legacy config shapes (pure).

    * ``servers``    — list of ``servers.json`` records (name/host/port/ae_title/
      poor_connectivity).
    * ``socket_cfg`` — parsed ``socket_config.json`` (global socket_host/port).
    * ``ai_services``— parsed ``servers_address.json`` ``services`` map (global AI
      endpoints; attributed to the profile whose host matches, else the active
      one).

    The active profile is the one whose host equals the global ``socket_host``
    (that is the server the app actually talks to today); otherwise the first.
    """
    servers = [s for s in (servers or []) if isinstance(s, dict)]
    socket_cfg = socket_cfg or {}
    services = {}
    if isinstance(ai_services, dict):
        services = ai_services.get("services") if isinstance(ai_services.get("services"), dict) else ai_services
    services = services or {}

    socket_host = str(socket_cfg.get("socket_host") or "").strip()
    socket_port = _coerce_int(socket_cfg.get("socket_port"), DEFAULT_SOCKET_PORT)

    def _services_for(host: str) -> dict[str, Optional[str]]:
        """Attribute the global AI services to the matching host only."""
        mods: dict[str, Optional[str]] = {k: None for k in MODULE_ENDPOINT_KEYS}
        mapping = {
            "ai_breast": services.get("breast"),
            "ai_boneage": services.get("boneage"),
            "ai_segmentation": services.get("segmentation"),
        }
        for key, val in mapping.items():
            if isinstance(val, str) and val.strip():
                ep_host = val.split(":", 1)[0].strip()
                if not host or ep_host == host:
                    mods[key] = val.strip()
        return mods

    profiles: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    active_id = ""
    for rec in servers:
        host = str(rec.get("host") or "").strip()
        name = str(rec.get("name") or host or "server").strip()
        pid = data_segment(name)
        # de-dup ids
        base_pid, n = pid, 2
        while pid in seen_ids:
            pid = f"{base_pid}-{n}"
            n += 1
        seen_ids.add(pid)
        # The socket port for the matching (active) host is the known-good global
        # one; other hosts default to the same standard port until verified.
        is_active_host = bool(socket_host) and host == socket_host
        prof = ServerProfile(
            id=pid,
            display_name=name,
            host=host,
            socket_port=socket_port if is_active_host else DEFAULT_SOCKET_PORT,
            dicom_port=_coerce_int(rec.get("port"), DEFAULT_DICOM_PORT),
            ae_title=str(rec.get("ae_title") or DEFAULT_AE_TITLE).strip() or DEFAULT_AE_TITLE,
            poor_connectivity=bool(rec.get("poor_connectivity", False)),
            enabled=True,
            modules=_services_for(host),
        )
        profiles.append(prof.to_dict())
        if is_active_host and not active_id:
            active_id = pid

    if not active_id and profiles:
        active_id = str(profiles[0]["id"])

    return {
        "schema_version": SCHEMA_VERSION,
        # The migrated/original center is the PRIMARY: it keeps the legacy single
        # data root so enabling the feature moves NO existing data.
        "primary_profile_id": active_id,
        "active_profile_id": active_id,
        "profiles": profiles,
    }


def _read_json(path: Path) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _migrate_from_legacy_files() -> dict[str, Any]:
    """Read the legacy config files from the config dir and build a document."""
    cfg = _config_dir()
    servers = _read_json(cfg / "servers.json")
    socket_cfg = _read_json(cfg / "socket_config.json")
    ai_services = _read_json(cfg / "servers_address.json")
    doc = build_profiles_from_legacy(
        servers if isinstance(servers, list) else [],
        socket_cfg if isinstance(socket_cfg, dict) else {},
        ai_services if isinstance(ai_services, dict) else {},
    )
    return doc


# ── document load / save ─────────────────────────────────────────────────────
def _normalize_document(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict):
        return {"schema_version": SCHEMA_VERSION, "active_profile_id": "", "profiles": []}
    raw_profiles = doc.get("profiles")
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(raw_profiles, list):
        for rec in raw_profiles:
            if not isinstance(rec, dict):
                continue
            prof = ServerProfile.from_dict(rec)
            pid = prof.id
            if pid in seen:
                continue
            seen.add(pid)
            profiles.append(prof.to_dict())
    active = str(doc.get("active_profile_id") or "").strip()
    if active not in seen:
        active = str(profiles[0]["id"]) if profiles else ""
    # primary = the center that keeps the legacy data root; defaults to active.
    primary = str(doc.get("primary_profile_id") or "").strip()
    if primary not in seen:
        primary = active
    return {
        "schema_version": _coerce_int(doc.get("schema_version"), SCHEMA_VERSION),
        "enabled": bool(doc.get("enabled", False)),
        "primary_profile_id": primary,
        "active_profile_id": active,
        "profiles": profiles,
    }


def load_profiles_document(*, migrate_if_missing: bool = True) -> dict[str, Any]:
    """Load (and normalize) the profiles document.

    When the file is absent and *migrate_if_missing* is True, build it from the
    legacy configs and persist it so subsequent reads are stable.
    """
    with _lock:
        path = profiles_config_path()
        raw = _read_json(path)
        if raw is None:
            if not migrate_if_missing:
                return {"schema_version": SCHEMA_VERSION, "active_profile_id": "", "profiles": []}
            doc = _normalize_document(_migrate_from_legacy_files())
            _write_document(doc)
            return doc
        return _normalize_document(raw)


def _write_document(doc: dict[str, Any]) -> None:
    path = profiles_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))


def save_profiles_document(doc: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        normalized = _normalize_document(doc)
        _write_document(normalized)
        return normalized


# ── high-level accessors ─────────────────────────────────────────────────────
def list_profiles() -> list[ServerProfile]:
    doc = load_profiles_document()
    return [ServerProfile.from_dict(p) for p in doc.get("profiles", [])]


def get_profile(profile_id: str) -> Optional[ServerProfile]:
    pid = str(profile_id or "").strip()
    if not pid:
        return None
    for prof in list_profiles():
        if prof.id == pid:
            return prof
    return None


def get_active_profile_id() -> str:
    return str(load_profiles_document().get("active_profile_id") or "")


def get_active_profile() -> Optional[ServerProfile]:
    doc = load_profiles_document()
    active = str(doc.get("active_profile_id") or "")
    for rec in doc.get("profiles", []):
        if str(rec.get("id")) == active:
            return ServerProfile.from_dict(rec)
    profiles = doc.get("profiles", [])
    return ServerProfile.from_dict(profiles[0]) if profiles else None


def set_active_profile_id(profile_id: str) -> bool:
    """Set the active profile.  Returns True if it exists and was set."""
    with _lock:
        pid = str(profile_id or "").strip()
        doc = load_profiles_document()
        ids = {str(p.get("id")) for p in doc.get("profiles", [])}
        if pid not in ids:
            return False
        doc["active_profile_id"] = pid
        _write_document(doc)
        return True


def upsert_profile(profile: ServerProfile) -> dict[str, Any]:
    """Insert or update *profile* (matched by id).  Returns the saved document."""
    with _lock:
        doc = load_profiles_document()
        profiles = doc.get("profiles", [])
        out: list[dict[str, Any]] = []
        replaced = False
        for rec in profiles:
            if str(rec.get("id")) == profile.id:
                out.append(profile.to_dict())
                replaced = True
            else:
                out.append(rec)
        if not replaced:
            out.append(profile.to_dict())
        doc["profiles"] = out
        if not doc.get("active_profile_id"):
            doc["active_profile_id"] = profile.id
        return save_profiles_document(doc)


def delete_profile(profile_id: str) -> dict[str, Any]:
    """Delete a profile by id.  The active id falls back to the first remaining."""
    with _lock:
        pid = str(profile_id or "").strip()
        doc = load_profiles_document()
        doc["profiles"] = [p for p in doc.get("profiles", []) if str(p.get("id")) != pid]
        if str(doc.get("active_profile_id")) == pid:
            doc["active_profile_id"] = (
                str(doc["profiles"][0]["id"]) if doc.get("profiles") else ""
            )
        return save_profiles_document(doc)


def set_feature_enabled(enabled: bool) -> dict[str, Any]:
    """Persist the top-level multi-server ``enabled`` flag (config-based opt-in).

    Note: the env var ``AIPACS_SERVER_PROFILES`` still overrides this when set.
    Takes effect on the next app start (the data root + socket target resolve at
    startup from the active profile).
    """
    with _lock:
        doc = load_profiles_document()
        doc["enabled"] = bool(enabled)
        return save_profiles_document(doc)


def is_feature_enabled_in_config() -> bool:
    """The persisted ``enabled`` flag only (ignores the env override)."""
    try:
        return bool(load_profiles_document(migrate_if_missing=False).get("enabled", False))
    except Exception:
        return False


# ── lookup helpers (used by the socket-routing + login layers) ──────────────
def find_profile_by_host(host: str) -> Optional[ServerProfile]:
    h = str(host or "").strip()
    if not h:
        return None
    for prof in list_profiles():
        if prof.host == h:
            return prof
    return None


def find_profile_by_name(name: str) -> Optional[ServerProfile]:
    n = str(name or "").strip().lower()
    if not n:
        return None
    for prof in list_profiles():
        if prof.display_name.strip().lower() == n or prof.id.strip().lower() == n:
            return prof
    return None


def find_profile_for_server(server: dict[str, Any] | None) -> Optional[ServerProfile]:
    """Match a *selectable-server* dict (name/host) to a profile."""
    if not isinstance(server, dict):
        return None
    return find_profile_by_name(str(server.get("name") or "")) or find_profile_by_host(
        str(server.get("host") or "")
    )


def socket_port_for_server(server: dict[str, Any] | None) -> int:
    """Resolve the **socket** port for a selectable-server dict.

    Prefers the matching profile's per-server ``socket_port``; falls back to the
    standard :data:`DEFAULT_SOCKET_PORT` (50052) when no profile matches.  This
    is what lets a second center live on its own socket port instead of the
    historical global one.
    """
    prof = find_profile_for_server(server)
    return int(prof.socket_port) if prof else DEFAULT_SOCKET_PORT


def active_module_endpoint(name: str) -> Optional[str]:
    """The ACTIVE profile's endpoint for module *name* (e.g. ``reception_api``,
    ``ai_breast``, ``ai_boneage``, ``ai_segmentation``, ``mammography``,
    ``bonj``), or ``None`` when the feature is off / the slot is unset.

    Consumers call this first and fall back to their existing global config when
    it returns ``None`` — so reception/workflow + AI endpoints follow the active
    center, with byte-identical legacy behaviour when the feature is off.
    """
    if not server_profiles_enabled():
        return None
    prof = get_active_profile()
    return prof.module_endpoint(name) if prof else None


# ── data-namespace helpers (used by the per-profile data-root layer) ────────
def get_primary_profile_id() -> str:
    """The PRIMARY/original center — it keeps the legacy single data root.

    Defaults to the active profile when unset (so a single-center user is always
    their own primary and never gets a ``servers/<id>`` subfolder).
    """
    try:
        doc = load_profiles_document(migrate_if_missing=False)
        pid = str(doc.get("primary_profile_id") or "").strip()
        return pid or str(doc.get("active_profile_id") or "")
    except Exception:
        return ""


def profile_segment(profile_id: str) -> str:
    """Data-namespace segment for *profile_id*.

    The PRIMARY center maps to ``"default"`` (the legacy ``user_data`` root, so
    enabling multi-server moves NO existing data); every other center maps to
    its own slug → ``user_data/servers/<slug>/``.
    """
    pid = str(profile_id or "").strip()
    if not pid or pid == get_primary_profile_id():
        return "default"
    return data_segment(pid)


def active_data_segment() -> str:
    """Filesystem-safe namespace for the *active* profile (or 'default').

    Returns ``"default"`` when profiles are disabled, none is active, or the
    active center is the primary — preserving the legacy single-root layout.
    """
    if not server_profiles_enabled():
        return "default"
    active = get_active_profile_id()
    return profile_segment(active) if active else "default"


# ── per-server clinical-data root (data separation + per-server delete) ──────
def clinical_data_root(
    user_data_root: "os.PathLike[str] | str",
    *,
    enabled: Optional[bool] = None,
    segment: Optional[str] = None,
) -> Path:
    """Resolve the CLINICAL data root, namespaced per active server.

    * Feature **off** (default) → returns ``user_data_root`` unchanged, so the
      legacy single-root layout is byte-identical.
    * Feature **on** → returns ``user_data_root/servers/<segment>`` so each
      center's database + patient files live in their own tree (no PatientID /
      StudyInstanceUID collisions, and a center's data is deletable on its own).

    ``enabled`` / ``segment`` are injectable for tests; in production both are
    resolved from the active profile.
    """
    base = Path(user_data_root)
    if enabled is None:
        enabled = server_profiles_enabled()
    if not enabled:
        return base
    seg = segment if segment is not None else active_data_segment()
    if not seg or seg == "default":
        return base
    return base / "servers" / data_segment(seg)


def server_data_root(user_data_root: "os.PathLike[str] | str", profile_id: str) -> Path:
    """The clinical-data root for a SPECIFIC profile.

    PRIMARY center → the legacy ``user_data`` root (its patients/database sit at
    ``user_data/patients`` and ``user_data/database``); every other center →
    ``user_data/servers/<slug>/``.
    """
    base = Path(user_data_root)
    seg = profile_segment(profile_id)
    return base if (not seg or seg == "default") else base / "servers" / seg


def delete_server_data(user_data_root: "os.PathLike[str] | str", profile_id: str) -> bool:
    """Delete ONE center's clinical data (db + dicom + thumbnails + attachments).

    * Secondary center → remove its whole ``servers/<slug>/`` tree.
    * Primary center → remove only the clinical subdirs (``patients`` +
      ``database``) at the legacy root, never the shared ``user_data`` itself
      (logs/config/education stay).

    Returns True if the clinical data is gone afterwards (incl. already-absent).
    Never raises. The CALLER must ensure this is not the currently-active center
    with open DB handles (delete after switching away / on restart) — a locked
    ``dicom.db`` on Windows would otherwise survive.
    """
    import shutil

    root = server_data_root(user_data_root, profile_id)
    base = Path(user_data_root)
    try:
        if root == base:
            # primary / legacy root: only the clinical subtrees
            ok = True
            for sub in ("patients", "database"):
                target = base / sub
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                    ok = ok and not target.exists()
            return ok
        if not root.exists():
            return True
        shutil.rmtree(root, ignore_errors=True)
        return not root.exists()
    except Exception:
        return False
