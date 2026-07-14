# -*- coding: utf-8 -*-
"""Internal-center (INO) assignment — isolated API service + façade.

This is the **separate backend path** for INO's *internal, same-center*
assignment (assign a radiologist / typist to a reception's studies). It is
deliberately isolated from the AI-PACS **Consultation / External Assignment**
workflow and must **never** touch it.

Hard isolation rules (enforced by `tests/code/network/test_ino_assignment.py`):
* Imports ONLY `reception_api_config`, `socket_token_manager`, and the two
  internal-assignment sibling modules. It imports **nothing** from
  `cloud_consultation` / `education` / Google Drive / Identity / payment.
* No image upload, no Drive, no website submission, no payment, no cross-center.

INO assignment contract — TWO services (ASSIGN_CLIENT_GUIDE_FA + live checks 2026-07-10):
  * RIS reception REST  (:8080) — the eligible-USER lists (verified 200 here):
      GET  {ris:8080}/api/personnel                 → radiologists / physicians (ris_personnel)
      GET  {ris:8080}/api/AdminUser/getCenterUsers  → center users / typists   (ris_user)
  * PACS HTTP           (:8000) — the ASSIGN write/read (the PACS-client path):
      PUT  {pacs:8000}/api/patients/{ReceptionID}/assign
           { assign_type, assignee_id, assignee_name, assignee_source, study_uid }
      GET  {pacs:8000}/api/patients/{ReceptionID}/assign  → { assignment: {...} }
  ReceptionID = the NUMERIC reception number (PatientID in PACS). Assign supports
  BOTH radiologist and typist and fires the targeted `study_assigned` socket event.
  (Earlier 404s were from hitting the assign paths on :8080; they live on :8000.
   The socket alt is `AssignStudy` on :50052 — a later, deeper integration.)

Auth reuses the logged-in user's JWT (`SocketTokenManager`) — the same
credentials the physician logs in with. Center-specific base URL is configurable
(env → `config/ino_assignment_config.json` → reception base fallback).

**Default ON** (2026-07-10). Turn it off with env `AIPACS_INO_ASSIGNMENT=0`
(or `false`/`off`/`no`) or config `{"enabled": false}`. Dedicated logger:
``ino_assignment``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any, Callable, Dict, List, Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

from modules.network.reception_api_config import (
    get_reception_api_base_url,
    get_reception_api_timeout,
)
from modules.network.socket_token_manager import get_socket_token_manager
from modules.network.ino_assignment_models import (
    ACTION_ASSIGNED,
    ACTION_FAILED,
    ACTION_REASSIGNED,
    ACTION_STATUS_CHANGED,
    ACTION_UNASSIGNED,
    ASSIGN_TYPE_RADIOLOGIST,
    ASSIGN_TYPE_TYPIST,
    ASSIGNMENT_STATUSES,
    STATUS_REMOVED,
    AssignableUser,
    AssignmentRecord,
    default_source_for_type,
    is_valid_assign_type,
    is_valid_source,
    normalize_status,
)
from modules.network import ino_assignment_history as _history

logger = logging.getLogger("ino_assignment")

# --- Feature gate (default OFF) ----------------------------------------------
# Default ON (2026-07-10). Disable explicitly with env AIPACS_INO_ASSIGNMENT=0
# or config {"enabled": false}. These falsey tokens turn it off.
_ENV_DISABLE_TOKENS = {"0", "false", "off", "no"}

_CONFIG_FILENAME = "ino_assignment_config.json"
# Eligible-user sources (live-verified on this center's INO :8080 with the
# reception token). NOTE: the guide's unified ``/api/assign/users`` returns 404
# here — the real sources are split by role:
_PERSONNEL_PATH = "/api/personnel"                    # radiologists / physicians
_CENTER_USERS_PATH = "/api/AdminUser/getCenterUsers"  # center users / typists
# WRITE / READ assign endpoints — the PACS client contract (ASSIGN_CLIENT_GUIDE_FA
# §3.2/§3.3). These live on the PACS HTTP service (:8000), NOT the RIS reception
# REST (:8080). `patient_id` == the NUMERIC ReceptionID. Supports radiologist AND
# typist. Assigning here triggers the targeted `study_assigned` socket event.
#   PUT  {pacs:8000}/api/patients/{ReceptionID}/assign
#        { assign_type, assignee_id, assignee_name, assignee_source, study_uid }
#   GET  {pacs:8000}/api/patients/{ReceptionID}/assign  → { assignment: {...} }
# (The earlier 404 was from hitting :8080; on :8000 these exist. The RIS-side
#  PATCH /api/Reports/reception/{mongoId}/radiologist is only the RIS bridge that
#  itself calls this PACS endpoint — a PACS client uses this directly.)
_ASSIGN_PATH = "/api/patients/{rid}/assign"
_PERMISSION_PHRASES = ("مجاز نیست", "دسترسی", "مجوز", "permission", "forbidden", "not allowed", "unauthorized")


# --- Config ------------------------------------------------------------------
def _config() -> Dict[str, Any]:
    try:
        from PacsClient.utils.config import SOCKET_CONFIG_PATH

        path = os.path.join(str(SOCKET_CONFIG_PATH), _CONFIG_FILENAME)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def is_enabled() -> bool:
    """True when the internal-assignment feature is on. **Default ON.**

    Precedence: env ``AIPACS_INO_ASSIGNMENT`` (explicit on/off) → config
    ``enabled`` (default True) → True. Set the env to 0/false/off/no or config
    ``{"enabled": false}`` to turn it off.
    """
    val = os.environ.get("AIPACS_INO_ASSIGNMENT")
    if val is not None and val.strip() != "":
        return val.strip().lower() not in _ENV_DISABLE_TOKENS
    try:
        return bool(_config().get("enabled", True))
    except Exception:
        return True


def _derive_pacs_http_base() -> str:
    """The PACS HTTP base (``http://{host}:8000``) for the ACTIVE server profile.

    Per ASSIGN_CLIENT_GUIDE_FA the assign REST API runs on the **PACS** host, port
    **8000** — a different service from the RIS reception REST (:8080).

    2026-07-14: this used to derive the host from the **reception** base URL and
    swap the port to 8000. That is wrong: reception and PACS are different
    services and, at some centers, different machines (here the profile host is
    ``192.168.2.222`` while reception is the port-forwarded ``81.16.117.196`` —
    both answered, so the defect was latent). The PACS HTTP service lives on the
    SAME host the imaging socket talks to, i.e. the ACTIVE SERVER PROFILE's host,
    which is what Server Settings configures. Per-profile ``pacs_http`` slot wins.
    Never returns a hard-coded address.
    """
    try:
        from PacsClient.utils.server_profiles import active_pacs_http_base

        base = active_pacs_http_base()
        if base:
            return base.rstrip("/")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[ino-assignment] profile PACS base unavailable: %s", exc)
    # Legacy fallback ONLY (no profile configured at all): the reception host.
    try:
        from urllib.parse import urlparse

        recv = get_reception_api_base_url() or ""
        u = urlparse(recv if "://" in recv else "http://" + recv)
        host = u.hostname or ""
        if host:
            return f"{(u.scheme or 'http')}://{host}:8000"
    except Exception:
        pass
    return ""


def get_ino_assignment_base_url() -> str:
    """Resolve the INO **assign** API base URL (the PACS HTTP service).

    Precedence: env override → ``config/ino_assignment_config.json``
    (``assignment_api_base_url``) → derived PACS host ``:8000`` → reception base.
    The assign endpoints (``PUT /api/patients/{id}/assign``) live on the PACS host
    port 8000, NOT the reception REST (:8080), so the default derives :8000.
    """
    for key in ("AIPACS_INO_ASSIGNMENT_BASE_URL", "INO_ASSIGNMENT_BASE_URL"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val.rstrip("/")
    try:
        configured = str(_config().get("assignment_api_base_url") or "").strip()
        if configured:
            return configured.rstrip("/")
    except Exception:
        pass
    derived = _derive_pacs_http_base()
    if derived:
        return derived.rstrip("/")
    try:
        return get_reception_api_base_url().rstrip("/")
    except Exception:
        return ""


# Transport for the ASSIGN write: "socket" (:50052 AssignStudy) or "rest" (PACS
# :8000 HTTP). **Socket is the DEFAULT** — it is the same authenticated imaging
# socket AI-PACS already holds, works without the PACS HTTP service being exposed,
# and is the documented PACS-client path (guide §4). REST is the alternative /
# fallback (used when explicitly selected, or when the socket can't connect).
TRANSPORT_REST = "rest"
TRANSPORT_SOCKET = "socket"
_DEFAULT_TRANSPORT = TRANSPORT_SOCKET


def get_ino_assignment_transport() -> str:
    val = (os.environ.get("AIPACS_INO_ASSIGNMENT_TRANSPORT") or "").strip().lower()
    if val in (TRANSPORT_REST, TRANSPORT_SOCKET):
        return val
    try:
        cv = str(_config().get("transport") or "").strip().lower()
        if cv in (TRANSPORT_REST, TRANSPORT_SOCKET):
            return cv
    except Exception:
        pass
    return _DEFAULT_TRANSPORT


def get_config_path() -> str:
    """Absolute path to ``ino_assignment_config.json`` (or "" if unresolved)."""
    try:
        from PacsClient.utils.config import SOCKET_CONFIG_PATH

        return os.path.join(str(SOCKET_CONFIG_PATH), _CONFIG_FILENAME)
    except Exception:
        return ""


def save_ino_assignment_config(updates: Dict[str, Any]) -> bool:
    """Merge ``updates`` into ``ino_assignment_config.json`` (used by Settings).

    Only the provided keys are changed; the rest of the file (incl. the ``note``)
    is preserved. Returns True on success.
    """
    path = get_config_path()
    if not path:
        return False
    try:
        data: Dict[str, Any] = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
                if isinstance(loaded, dict):
                    data = loaded
        data.update(updates or {})
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("[ino-assignment] failed to save config: %s", exc)
        return False


# --- Helpers -----------------------------------------------------------------
def _headers() -> Optional[dict]:
    try:
        tok = get_socket_token_manager().get_token()
    except Exception:
        tok = None
    if not tok:
        return None
    return {"Authorization": f"Bearer {tok}", "Accept": "application/json", "Content-Type": "application/json"}


def _classify(status_code: int, message: str) -> str:
    msg = (message or "").lower()
    if status_code == 403 or any(p in (message or "") or p in msg for p in _PERMISSION_PHRASES):
        return "permission"
    if status_code == 401:
        return "auth"
    if status_code and status_code >= 400:
        return "http"
    return ""


def _current_user_id() -> str:
    try:
        user = get_socket_token_manager().get_user() or {}
        return str(user.get("id") or user.get("_id") or user.get("user_id") or "")
    except Exception:
        return ""


# --- Permission hook (client-side; server still enforces) --------------------
def can_assign(assign_type: str) -> bool:
    """Single place for CLIENT-SIDE permission gating of internal assignment.

    Server-side INO enforcement is authoritative; this hook lets the UI hide/
    disable an action the user's role can't perform (mirroring INO's own web
    UI). It currently returns True (server enforces + the service surfaces any
    403); wire the INO permission-id checks here when the permission catalog is
    available. Kept separate from any consultation permission logic.
    """
    return True


# --- Low-level REST client ----------------------------------------------------
class InoAssignmentClient:
    """Thin REST client for INO's internal assignment endpoints. Never raises."""

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        # Two distinct services (ASSIGN_CLIENT_GUIDE_FA):
        #   * ASSIGN base  = PACS HTTP :8000  → PUT/GET /api/patients/{id}/assign
        #   * RIS base     = reception :8080  → the eligible-user list endpoints
        # `base_url` (if given) overrides the assign base (kept for tests/config).
        self._base_url = (base_url or get_ino_assignment_base_url()).rstrip("/")
        try:
            self._ris_base = (get_reception_api_base_url() or self._base_url).rstrip("/")
        except Exception:
            self._ris_base = self._base_url
        try:
            self._timeout = int(timeout) if timeout else max(8, int(get_reception_api_timeout()))
        except Exception:
            self._timeout = 8

    def _fail(self, message: str, status: int = 0) -> Dict[str, Any]:
        kind = _classify(status, message)
        return {
            "ok": False,
            "status": status,
            "message": message,
            "permission_denied": kind == "permission",
            "auth_error": kind == "auth",
        }

    def _get_rows(self, path: str) -> Dict[str, Any]:
        """GET a list endpoint; returns {"ok": True, "rows": [...]} or a _fail."""
        if requests is None:
            return self._fail("requests unavailable")
        headers = _headers()
        if not headers:
            return self._fail("no active session token", 401)
        try:
            # User-list endpoints live on the RIS reception service (:8080).
            r = requests.get(self._ris_base + path, headers=headers, timeout=self._timeout)
            if r.status_code != 200:
                return self._fail(_message_of(r), r.status_code)
            body = r.json()
            data = body.get("data") if isinstance(body, dict) else body
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = data.get("users") or data.get("items") or data.get("results") or []
            else:
                rows = []
            return {"ok": True, "rows": rows}
        except Exception as exc:
            return self._fail(f"request failed: {exc}")

    def list_assignable_users(
        self,
        assign_type: str,
        source: str = "all",
        search: str = "",
        role: str = "",
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Eligible INO users for the Internal tab.

        radiologist ← ``/api/personnel``; typist ← ``/api/AdminUser/getCenterUsers``.
        ``assign_type`` "" / "all" merges both. Uses the reception token (same
        realm — live-verified). This is the INO source ONLY — never the
        consultation registry.
        """
        if requests is None:
            return self._fail("requests unavailable")
        want_rad = assign_type in (ASSIGN_TYPE_RADIOLOGIST, "", "all", None)
        want_typ = assign_type in (ASSIGN_TYPE_TYPIST, "", "all", None)
        users: List[AssignableUser] = []

        if want_rad:
            res = self._get_rows(_PERSONNEL_PATH)
            if not res.get("ok"):
                if assign_type == ASSIGN_TYPE_RADIOLOGIST:
                    return res  # surface the failure when it's the only requested type
            else:
                users += [AssignableUser.from_personnel(x) for x in res["rows"]]

        if want_typ:
            res = self._get_rows(_CENTER_USERS_PATH)
            if not res.get("ok"):
                if assign_type == ASSIGN_TYPE_TYPIST:
                    return res
            else:
                users += [AssignableUser.from_center_user(x) for x in res["rows"]]

        # Only active users; optional client-side search on name/username.
        users = [u for u in users if u.is_active and (u.full_name or u.username)]
        if search:
            s = search.strip().lower()
            users = [u for u in users if s in (u.full_name or "").lower() or s in (u.username or "").lower()]
        if limit and limit > 0:
            users = users[:limit]
        return {"ok": True, "status": 200, "users": users}

    def get_assignment(self, reception_id) -> Dict[str, Any]:
        """Read the reception's current assignment (PACS ``GET /api/patients/{id}/assign``).

        Returns ``assignment`` = ``{radiologist:{id,name,source}, typist:{...}, …}``.
        Absence of an assignment is not an error.
        """
        if requests is None:
            return self._fail("requests unavailable")
        headers = _headers()
        if not headers:
            return self._fail("no active session token", 401)
        url = self._base_url + _ASSIGN_PATH.format(rid=reception_id)  # PACS :8000
        try:
            # Pooled keep-alive session — this is called once per visible reception
            # when the patient list refreshes, so the per-call TCP handshake was
            # pure overhead. See modules/network/http_session.py.
            from modules.network.http_session import http_get
            r = http_get(url, base_url=self._base_url, headers=headers,
                         timeout=self._timeout)
            if r.status_code != 200:
                return self._fail(_message_of(r), r.status_code)
            body = r.json() if _is_json(r) else {}
            return {"ok": True, "status": 200,
                    "assignment": (body or {}).get("assignment") or {}, "raw": body}
        except Exception as exc:
            return self._fail(f"request failed: {exc}")

    def assign(
        self,
        reception_id,
        assign_type: str,
        assignee_id: str,
        assignee_name: str = "",
        assignee_source: str = "",
        study_uid: str = "",
        allow_empty: bool = False,
    ) -> Dict[str, Any]:
        """Assign a radiologist or typist to a reception (PACS client contract).

        ``allow_empty=True`` permits an EMPTY ``assignee_id`` — that is how an
        UNASSIGN is expressed (the contract has no dedicated unassign endpoint);
        the server's real answer is returned, never a faked success.

        ``PUT {pacs:8000}/api/patients/{ReceptionID}/assign`` with
        ``{assign_type, assignee_id, assignee_name, assignee_source, study_uid}``.
        ``reception_id`` is the numeric ReceptionID. Empty ``study_uid`` = all
        studies of the reception. This is the documented PACS-client path; it
        also fires the targeted ``study_assigned`` socket notification.
        """
        if requests is None:
            return self._fail("requests unavailable")
        if not is_valid_assign_type(assign_type):
            return self._fail(f"invalid assign_type: {assign_type}")
        if not str(assignee_id or "").strip() and not allow_empty:
            return self._fail("missing assignee id")
        source = assignee_source or default_source_for_type(assign_type)
        if not is_valid_source(source):
            return self._fail(f"invalid assignee_source: {source}")
        headers = _headers()
        if not headers:
            return self._fail("no active session token", 401)
        url = self._base_url + _ASSIGN_PATH.format(rid=reception_id)  # PACS :8000
        payload = {
            "assign_type": assign_type,
            "assignee_id": str(assignee_id),
            "assignee_name": assignee_name or "",
            "assignee_source": source,
            "study_uid": study_uid or "",
        }
        socket_params = {"patient_id": str(reception_id), **payload}
        uid = _current_user_id()
        rest_headers = dict(headers)
        if uid:
            rest_headers["X-User-Id"] = uid

        def _do_rest() -> Dict[str, Any]:
            try:
                r = requests.put(url, json=payload, headers=rest_headers, timeout=self._timeout)
                if r.status_code not in (200, 201):
                    return self._fail(_message_of(r), r.status_code)
                body = r.json() if _is_json(r) else {}
                return {"ok": True, "status": r.status_code, "raw": body,
                        "modified_count": (body or {}).get("modified_count")}
            except Exception as exc:
                # status 0 marks a connection-level failure (distinct from a 4xx/5xx).
                return self._fail(f"request failed: {exc}", 0)

        transport = get_ino_assignment_transport()
        if transport == TRANSPORT_SOCKET:
            # DEFAULT: assign over the imaging socket AI-PACS already holds.
            res = self._assign_via_socket(socket_params)
            if res.get("ok") or res.get("permission_denied") or res.get("auth_error"):
                return res
            logger.info("[ino-assignment] socket assign failed (%s); trying REST :8000",
                        res.get("message"))
            rest = _do_rest()
            if rest.get("ok"):
                return rest
            # BOTH failed. Return the answer that carries a REAL REASON.
            # The socket used to win unconditionally here, so a server that had
            # actually VALIDATED and refused the request (e.g. "assignee_id is
            # required" / HTTP 422) was reported to the user as the meaningless
            # "socket assign rejected". Prefer whichever side the SERVER answered:
            # a truthy REST status is a 4xx/5xx (it answered); `server_answered`
            # marks the same thing on the socket side.
            if res.get("server_answered"):
                return res
            if rest.get("status"):
                return rest
            return res
        # transport == rest → PACS :8000, socket fallback on a CONNECTION failure only
        res = _do_rest()
        if res.get("ok") or res.get("status"):  # truthy status = the server answered (4xx/5xx)
            return res
        logger.info("[ino-assignment] REST assign unreachable; trying socket fallback")
        fb = self._assign_via_socket(socket_params)
        return fb if fb.get("ok") else res

    def _assign_via_socket(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            tok = get_socket_token_manager().get_token()
        except Exception:
            tok = None
        try:
            from modules.network.ino_assignment_socket import assign_via_socket
        except Exception as exc:  # pragma: no cover - defensive
            return self._fail(f"socket transport unavailable: {exc}")
        return assign_via_socket(tok or "", params, timeout=self._timeout)


#: The server refuses an empty assignee on BOTH transports (verified 2026-07-14):
#:   socket AssignStudy → {"status":"error","error":"assignee_id is required"}
#:   REST  PUT /assign  → HTTP 422 {"type":"string_too_short","loc":["body","assignee_id"]}
#: Either one means "this server cannot remove an assignment", NOT a network fault.
_MISSING_ASSIGNEE_PHRASES = (
    "assignee_id is required",
    "assignee_id",
    "string_too_short",
    "at least 1 character",
    "field required",
)


def _is_missing_assignee_refusal(result: Dict[str, Any]) -> bool:
    """True when the server VALIDATED the request and rejected the empty assignee."""
    if int(result.get("status") or 0) in (400, 422):
        return True
    msg = str(result.get("message") or "").lower()
    return any(p in msg for p in _MISSING_ASSIGNEE_PHRASES)


def _is_json(resp) -> bool:
    return "application/json" in (resp.headers.get("content-type") or "")


def _message_of(resp) -> str:
    try:
        if _is_json(resp):
            b = resp.json()
            if isinstance(b, dict):
                return str(b.get("message") or b.get("error") or "")
        return (resp.text or "")[:200]
    except Exception:
        return ""


# --- Façade the (future) UI calls --------------------------------------------
class InternalAssignmentService:
    """High-level entry point for the internal-center assignment workflow.

    The future UI (separate button/dialog — provided in the next step) drives
    THIS service, never the consultation code. Applies the client-side
    permission hook, records the separate history, logs under ``ino_assignment``,
    and returns structured results the UI can render. Best-effort; never raises.
    """

    def __init__(self, base_url: Optional[str] = None):
        self._client = InoAssignmentClient(base_url)

    # -- reads --
    def list_users(self, assign_type: str, source: str = "all", search: str = "", limit: int = 200) -> Dict[str, Any]:
        if not is_enabled():
            return {"ok": False, "disabled": True, "message": "internal assignment feature disabled"}
        return self._client.list_assignable_users(assign_type, source=source, search=search, limit=limit)

    def current_assignment(self, reception_id) -> Dict[str, Any]:
        if not is_enabled():
            return {"ok": False, "disabled": True}
        return self._client.get_assignment(reception_id)

    # -- write --
    def assign(
        self,
        reception_id,
        assign_type: str,
        assignee_id: str,
        assignee_name: str = "",
        assignee_source: str = "",
        study_uid: str = "",
        *,
        is_reassignment: bool = False,
        comment: str = "",
    ) -> Dict[str, Any]:
        """Assign (or reassign) a radiologist/typist to a reception. Records the
        action (incl. the optional ``comment``) in the SEPARATE
        internal-assignment history."""
        if not is_enabled():
            return {"ok": False, "disabled": True, "message": "internal assignment feature disabled"}
        if not can_assign(assign_type):
            logger.warning("[ino-assignment] blocked by client permission hook: type=%s", assign_type)
            return {"ok": False, "permission_denied": True, "message": "not permitted (client policy)"}

        result = self._client.assign(
            reception_id, assign_type, assignee_id, assignee_name, assignee_source, study_uid
        )
        ok = bool(result.get("ok"))
        action = (ACTION_REASSIGNED if is_reassignment else ACTION_ASSIGNED) if ok else ACTION_FAILED
        try:
            _history.record(AssignmentRecord(
                reception_id=str(reception_id),
                assign_type=assign_type,
                assignee_id=str(assignee_id),
                assignee_name=assignee_name or "",
                assignee_source=assignee_source or default_source_for_type(assign_type),
                action=action,
                study_uid=study_uid or "",
                assigned_by=_current_user_id(),
                comment=str(comment or ""),
                server_ok=ok,
                message=str(result.get("message") or ""),
            ))
        except Exception:  # pragma: no cover - history must never break the action
            pass

        if not ok:
            kind = "PERMISSION" if result.get("permission_denied") else ("AUTH" if result.get("auth_error") else "ERROR")
            logger.warning(
                "[ino-assignment] assign FAILED (%s) reception=%s type=%s http=%s msg=%s",
                kind, reception_id, assign_type, result.get("status"), result.get("message"),
            )
        else:
            logger.info(
                "[ino-assignment] assigned reception=%s type=%s assignee=%s source=%s modified=%s",
                reception_id, assign_type, assignee_name or assignee_id,
                assignee_source or default_source_for_type(assign_type), result.get("modified_count"),
            )
        return result

    def unassign(self, reception_id, assign_type: str = ASSIGN_TYPE_RADIOLOGIST,
                 *, comment: str = "") -> Dict[str, Any]:
        """REMOVE the assignment on the SERVER (deactivate == cancel == unassign).

        ⚠ SERVER LIMITATION (verified 2026-07-14 against the live OpenAPI schema,
        not guessed). The assign API exposes exactly three routes:

            GET  /api/patients/{id}/assign
            PUT  /api/patients/{id}/assign   AssignPayload{assign_type,
                                             assignee_id (**minLength = 1**), ...}
            PUT  /api/patients/{id}/radiologist   (legacy)

        There is **no DELETE verb** (405) and ``assignee_id`` may not be empty, so
        an empty-assignee PUT — the only way the contract could express a clear —
        is rejected with **HTTP 422 string_too_short**. The server therefore has NO
        way to remove an assignment today.

        We still issue the correct request (so this starts working the moment the
        server drops ``minLength``), and we return the server's REAL answer. We do
        NOT record a local "removed" on failure: that would make this workstation
        show the patient as unassigned while the server — and every other
        workstation — still shows the assignment. The caller surfaces the error.

        The one-line server fix: allow ``assignee_id: ""`` on PUT /assign (clear
        ``radiologistId`` / ``radiologistName``), or add ``DELETE /assign``.
        """
        if not is_enabled():
            return {"ok": False, "disabled": True, "message": "internal assignment feature disabled"}
        if not can_assign(assign_type):
            return {"ok": False, "permission_denied": True, "message": "not permitted (client policy)"}
        result = self._client.assign(
            reception_id, assign_type, "", assignee_name="", assignee_source="",
            study_uid="", allow_empty=True,
        )
        ok = bool(result.get("ok"))
        if not ok and _is_missing_assignee_refusal(result):
            # Make the cause unmistakable instead of a raw validation dump / a
            # meaningless "socket assign rejected".
            result["unsupported_by_server"] = True
            result["message"] = (
                "This server cannot remove an assignment.\n\n"
                "Both transports reject an empty assignee:\n"
                "  • socket AssignStudy → \"assignee_id is required\"\n"
                "  • REST PUT /assign   → HTTP 422 (assignee_id minLength=1)\n"
                "and there is no DELETE endpoint (405).\n\n"
                "The assignment was NOT changed. Ask the PACS server to accept an "
                "empty assignee_id on assign (clearing radiologistId/Name), or to "
                "add DELETE /api/patients/{id}/assign."
            )
        try:
            _history.record(AssignmentRecord(
                reception_id=str(reception_id),
                assign_type=assign_type,
                assignee_id="",
                assignee_name="",
                assignee_source=default_source_for_type(assign_type),
                action=ACTION_UNASSIGNED if ok else ACTION_FAILED,
                assigned_by=_current_user_id(),
                server_ok=ok,
                message=str(result.get("message") or ""),
            ))
        except Exception:  # pragma: no cover
            pass
        logger.info("[ino-assignment] unassign reception=%s ok=%s msg=%s",
                    reception_id, ok, result.get("message"))
        return result

    def set_assignment_status(self, reception_id, status: str, *, comment: str = "") -> Dict[str, Any]:
        """Set the assignment LIFECYCLE status — THREE canonical states.

        ``removed`` (== the old deactivate / cancel / unassign, which all meant the
        same thing) is routed to :meth:`unassign`, a real SERVER call.
        ``active`` / ``completed`` have **no server endpoint** — the server's assign
        model has no status field at all — so they are recorded LOCALLY in the
        internal history (``server_ok=False``) and the result carries ``local: True``
        so the UI labels them honestly instead of implying server confirmation."""
        if not is_enabled():
            return {"ok": False, "disabled": True, "message": "internal assignment feature disabled"}
        st = normalize_status(status)
        if st not in ASSIGNMENT_STATUSES:
            return {"ok": False, "message": f"invalid assignment status: {status}"}
        if st == STATUS_REMOVED:
            return self.unassign(reception_id, comment=comment)
        try:
            _history.record(AssignmentRecord(
                reception_id=str(reception_id),
                assign_type="",
                assignee_id="",
                assignee_name="",
                assignee_source="",
                action=ACTION_STATUS_CHANGED,
                assignment_status=st,
                assigned_by=_current_user_id(),
                comment=str(comment or ""),
                server_ok=False,
                message="local status change (no INO endpoint for this state)",
            ))
        except Exception as exc:  # pragma: no cover
            logger.warning("[ino-assignment] status change not recorded: %s", exc)
            return {"ok": False, "message": str(exc)}
        logger.info("[ino-assignment] LOCAL status change reception=%s status=%s", reception_id, st)
        return {"ok": True, "local": True, "status_set": st}

    def history(self, reception_id=None, limit: int = 100) -> List[Dict[str, Any]]:
        if reception_id is not None:
            return _history.read_for_reception(reception_id, limit=limit)
        return _history.read_all(limit=limit)

    def assignment_details(self, reception_id) -> Optional[Dict[str, Any]]:
        """The current assignment (assignee / assigner / comment / when) enriched
        with the resolved lifecycle status — straight from the real record."""
        return _history.current_assignment_details(reception_id)


def get_internal_assignment_service(base_url: Optional[str] = None) -> InternalAssignmentService:
    """Return an InternalAssignmentService (the isolated internal-assignment entry point)."""
    return InternalAssignmentService(base_url)


# --- Non-blocking helper ------------------------------------------------------
def assign_async(
    reception_id,
    assign_type: str,
    assignee_id: str,
    assignee_name: str = "",
    assignee_source: str = "",
    study_uid: str = "",
    *,
    is_reassignment: bool = False,
    on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
    base_url: Optional[str] = None,
) -> None:
    """Run an assign on a daemon thread so the two REST calls never block the GUI.
    ``on_result`` (if given) is invoked with the structured result **on the
    worker thread** — the caller is responsible for marshalling to the GUI."""
    if not is_enabled():
        if on_result:
            try:
                on_result({"ok": False, "disabled": True})
            except Exception:
                pass
        return

    def _run() -> None:
        result = get_internal_assignment_service(base_url).assign(
            reception_id, assign_type, assignee_id, assignee_name, assignee_source,
            study_uid, is_reassignment=is_reassignment,
        )
        if on_result:
            try:
                on_result(result)
            except Exception:  # pragma: no cover
                logger.exception("[ino-assignment] on_result callback failed")

    try:
        threading.Thread(target=_run, name="INOAssignment", daemon=True).start()
    except Exception:  # pragma: no cover
        logger.exception("[ino-assignment] could not start async assign thread")


# INO internal assignment: default transport = socket (:50052); REST (:8000) alt.
# See docs/pipelines/internal-assignment-foundation.md.
