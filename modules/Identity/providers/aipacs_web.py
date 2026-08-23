"""AipacsWebIdentityProvider — pair the workstation with the AI-PACS web backend.

ADR-0006: the local Laravel backend ("consult-form") owns consultant profiles and
the internal/external consultation registry. This provider links the current
AI-PACS ``auth_user`` to an account on that backend by exchanging email+password
(or a pairing code) for a Sanctum token via
``POST {base}/api/v1/auth/workstation/pair``. The token is stored in the OS
keychain/DPAPI through :mod:`modules.Identity.secure_store` — exactly like the
Google provider, it NEVER touches the AI-PACS server login and never persists
raw credentials.

Configuration: ``config/identity/aipacs_web.json``::

    {"base_url": "http://localhost:8080/consult-form", "enabled": true}

Env override: ``AIPACS_WEB_BASE_URL`` (implies enabled).

The consultation layer obtains an :class:`AipacsWebClient` via
``get_capability_client(identity, Capability.CONSULTATION)`` (or the
:func:`get_aipacs_web_client` convenience) — it never sees the raw token
handling. ALL client network calls are guarded off the Qt GUI thread.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from modules.Identity.models import Capability, ExternalIdentity
from modules.Identity.providers.base import IdentityProvider

logger = logging.getLogger(__name__)

AIPACS_WEB_CONFIG_FILE = "aipacs_web.json"
_ENV_BASE_URL = "AIPACS_WEB_BASE_URL"
DEFAULT_TIMEOUT_SEC = 15
API_PREFIX = "/api/v1"


# ── configuration ──────────────────────────────────────────────────────────────
def aipacs_web_config_path():
    from modules.Identity.config import _config_root  # same root, no dir creation

    return _config_root() / "identity" / AIPACS_WEB_CONFIG_FILE


def load_aipacs_web_config() -> dict[str, Any]:
    """Resolve {base_url, enabled}. Env ``AIPACS_WEB_BASE_URL`` wins (and enables).

    Never raises; an unreadable config resolves to ``{"enabled": False}``.
    """
    env_url = (os.environ.get(_ENV_BASE_URL) or "").strip()
    if env_url:
        return {"base_url": env_url.rstrip("/"), "enabled": True}
    try:
        path = aipacs_web_config_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("base_url"):
                return {
                    "base_url": str(data["base_url"]).rstrip("/"),
                    "enabled": bool(data.get("enabled", True)),
                }
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("aipacs_web config read failed: %s", exc)
    return {"base_url": "", "enabled": False}


def aipacs_web_configured() -> bool:
    cfg = load_aipacs_web_config()
    return bool(cfg.get("enabled") and cfg.get("base_url"))


def save_aipacs_web_config(base_url: str, enabled: bool = True) -> bool:
    """Persist ``{base_url, enabled}`` to ``config/identity/aipacs_web.json``.

    Settings-tab writer companion to :func:`load_aipacs_web_config` — until now
    this file could only be created by hand (the provider's ``is_available``
    message literally told users to edit JSON). Merges into the existing file
    so unknown keys survive; the ``AIPACS_WEB_BASE_URL`` env override still
    wins at read time. Returns False instead of raising.
    """
    try:
        path = aipacs_web_config_path()
        payload: dict[str, Any] = {}
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    payload = data
        except Exception:  # unreadable file: rewrite it cleanly
            payload = {}
        payload["base_url"] = (base_url or "").strip().rstrip("/")
        payload["enabled"] = bool(enabled)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return True
    except Exception as exc:  # pragma: no cover - disk/permission problems
        logger.warning("aipacs_web config write failed: %s", exc)
        return False


def aipacs_web_env_override() -> str:
    """The env var name forcing the base URL, or "" (Settings-tab warning)."""
    return _ENV_BASE_URL if (os.environ.get(_ENV_BASE_URL) or "").strip() else ""


# ── the THREE addresses, and why they are not one ────────────────────────────
# ai-pacs.com serves ONE Laravel app through TWO web-server mounts, and they own
# different URL spaces (verified 2026-08-20 against the deployment):
#
#   API + forms/chat mount   https://ai-pacs.com/consult-form
#       …/api/v1/*           every call this client makes (base_url above)
#       …/forms-panel/*      staff login, chat console, visitors, Drive, greetings
#   Consultation portal      https://ai-pacs.com/ai-pacs-consultation
#       login, dashboard, consultations, consultants, profile, library, sharing,
#       admin
#
# They are NOT nested: the portal mount 404s `api` and `forms-panel`, and the
# consult-form mount 404s `ai-pacs-consultation` (both by .htaccess rule). So the
# portal address CANNOT be produced by appending to base_url — it is derived from
# the same host, or set explicitly with a ``portal_url`` key in aipacs_web.json
# for a deployment that puts the portal somewhere else.
PORTAL_PATH = "/ai-pacs-consultation"
STAFF_PANEL_PATH = "/forms-panel"


def portal_url() -> str:
    """Human-facing AI-PACS Consultation portal root, or "" if unknown.

    Where consultants, the education library, sharing and the consultant's own
    profile live. Explicit ``portal_url`` in the config wins; otherwise the
    scheme+host of ``base_url`` plus :data:`PORTAL_PATH`. Never raises.
    """
    try:
        data: dict[str, Any] = {}
        path = aipacs_web_config_path()
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        explicit = str(data.get("portal_url") or "").strip().rstrip("/")
        if explicit:
            return explicit
        base = str(load_aipacs_web_config().get("base_url") or "").strip()
        if not base:
            return ""
        from urllib.parse import urlsplit

        parts = urlsplit(base)
        if not parts.scheme or not parts.netloc:
            return ""
        return f"{parts.scheme}://{parts.netloc}{PORTAL_PATH}"
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("portal url resolution failed: %s", exc)
        return ""


def staff_panel_url() -> str:
    """Staff (forms + chat) panel root, or "".

    This one IS under ``base_url`` — the panel and the API share a mount.
    """
    base = str(load_aipacs_web_config().get("base_url") or "").strip().rstrip("/")
    return f"{base}{STAFF_PANEL_PATH}" if base else ""


# ── errors ─────────────────────────────────────────────────────────────────────
class AipacsWebError(RuntimeError):
    """Clean, user-presentable error from the AI-PACS web API client.

    ``status_code`` carries the HTTP status when there was one, and ``None``
    when the request never reached a response (DNS, refused connection,
    timeout) or when the failure was local.

    WHY IT EXISTS. A 401 used to be distinguishable from every other failure
    only by matching the message string, which is fine for a dialog that shows
    the message and wrong for a long-lived polling client: "the token is dead,
    discard it and ask the operator to sign in again" and "the wifi dropped,
    back off and retry" are opposite responses, and a poller cannot tell them
    apart from prose. Additive — every existing caller ignores it.
    """

    def __init__(self, message: str = "", *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _extract_error(resp) -> str:
    """Best-effort human message from a Laravel error response."""
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error") or ""
            errors = data.get("errors")
            if isinstance(errors, dict) and errors:
                first = next(iter(errors.values()))
                if isinstance(first, list) and first:
                    msg = f"{msg} {first[0]}".strip() if msg else str(first[0])
            if msg:
                return str(msg)
    except Exception:
        pass
    return f"HTTP {getattr(resp, 'status_code', '?')} from the consultation server"


# ── pairing (token exchange) ───────────────────────────────────────────────────
def default_device_name() -> str:
    try:
        import platform

        return f"AI-PACS Workstation ({platform.node() or 'unknown'})"
    except Exception:  # pragma: no cover - defensive
        return "AI-PACS Workstation"


def pair_workstation(
    base_url: str,
    credentials: dict[str, Any],
    *,
    device_name: str = "",
    session=None,
    timeout: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """``POST /auth/workstation/pair`` → ``{"token": ..., "user": {...}}``.

    ``credentials`` carries either ``email`` + ``password`` or ``pairing_code``.
    BLOCKING network call — callers must run it off the Qt GUI thread.
    """
    from modules.Identity.thread_guard import assert_off_gui_thread

    assert_off_gui_thread("aipacs_web pairing")

    creds = dict(credentials or {})
    payload: dict[str, Any] = {"device_name": device_name or default_device_name()}
    if creds.get("pairing_code"):
        payload["pairing_code"] = str(creds["pairing_code"]).strip()
    elif creds.get("email") and creds.get("password"):
        payload["email"] = str(creds["email"]).strip()
        payload["password"] = str(creds["password"])
    else:
        raise AipacsWebError(
            "Provide your AI-PACS web email and password, or a pairing code."
        )

    if session is None:
        import requests

        session = requests.Session()
    url = f"{base_url.rstrip('/')}{API_PREFIX}/auth/workstation/pair"
    try:
        # Accept header is REQUIRED: without it Laravel answers validation
        # errors with a 302 HTML redirect instead of 422 JSON (live-link
        # debugging, 2026-06-11).
        resp = session.post(
            url, json=payload, timeout=timeout,
            headers={"Accept": "application/json"},
        )
    except Exception as exc:
        raise AipacsWebError(f"Could not reach the consultation server: {exc}")
    # The Laravel pair endpoint returns 201 Created (200 kept for tolerance) —
    # caught by the local integration test 2026-06-10.
    if getattr(resp, "status_code", 0) not in (200, 201):
        raise AipacsWebError(_extract_error(resp))
    try:
        data = resp.json()
    except Exception:
        raise AipacsWebError("Unexpected response from the consultation server.")
    if not isinstance(data, dict) or not data.get("token"):
        raise AipacsWebError("Pairing did not return an access token.")
    return data


# ── Gmail attestation (ADR-0008 identity bridge) ──────────────────────────────
# The user, already logged into the workstation, proves ownership of a Gmail via
# a TRANSIENT Google OAuth (openid + email scopes ONLY — never Drive). The
# resulting ID TOKEN goes to the Laravel backend (`link-google`), which verifies
# it and returns a Sanctum token. CRITICAL invariant: this attestation must NOT
# store a personal Google identity (the standing Google identity is the shared
# hub Drive account, ADR-0004) — we capture id_token + subject, then DISCARD the
# OAuth credentials (no secure_store write for "google").

ATTEST_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


def _decode_id_token_payload(id_token: str) -> dict[str, Any]:
    """Decode a JWT payload locally (base64url, NO signature verification).

    The server is the verifier (Laravel checks signature/audience/expiry); we
    only need ``email`` + ``sub`` to sanity-check the account the user picked.
    """
    import base64

    try:
        parts = str(id_token).split(".")
        if len(parts) < 2:
            raise ValueError("not a JWT")
        seg = parts[1]
        seg += "=" * (-len(seg) % 4)  # restore base64url padding
        payload = json.loads(base64.urlsafe_b64decode(seg.encode("ascii")))
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        return payload
    except Exception as exc:
        raise AipacsWebError(f"Google returned an unreadable ID token: {exc}")


def attest_gmail(gmail: str = "", *, open_url_cb=None) -> dict[str, Any]:
    """Prove ownership of a Google account via a transient OAuth. BLOCKING.

    Returns ``{"id_token": str, "subject": str, "email": str}``. Uses ONLY the
    openid+email scopes (never Drive) with ``prompt='select_account'`` so the
    user can pick a different account than the hub Drive account. The OAuth
    credentials are discarded after the ID token is extracted — nothing is
    written to secure_store and no Google identity is created.

    ``gmail`` is OPTIONAL (unified one-step login, owner directive
    2026-06-11): when empty, the entered-vs-signed-in comparison is skipped
    and the Google-verified email is simply returned — the server decides
    authorization. When provided, a mismatch with the signed-in account still
    raises (admin/testing path).

    ``open_url_cb`` optionally overrides how the consent URL is opened
    (default: the Google provider's embedded-browser-or-system-browser
    pattern). Raises :class:`AipacsWebError` with a clean message on mismatch,
    cancellation, or a missing client config.
    """
    from modules.Identity.thread_guard import assert_off_gui_thread

    assert_off_gui_thread("aipacs_web gmail attestation")

    entered = (gmail or "").strip()
    if entered and "@" not in entered:
        raise AipacsWebError("Enter the Gmail address you want to link.")

    from modules.Identity.config import google_oauth_path, load_google_client_config

    client_config = load_google_client_config()
    if not client_config:
        raise AipacsWebError(
            "Google OAuth client not configured. Add your Desktop-app client "
            f"JSON at: {google_oauth_path()}"
        )

    from modules.Identity.providers.google import oauth_flow

    creds = None
    try:
        try:
            creds = oauth_flow.run_installed_app_flow(
                client_config,
                scopes=list(ATTEST_SCOPES),
                auth_url_kwargs={"prompt": "select_account"},
                open_url_cb=open_url_cb,
                # ADR-0009 D5: Gmail attestation stays in the internal Web
                # Browser module — never the external system browser. (Honoured
                # only when no explicit open_url_cb is supplied.)
                require_embedded=True,
            )
        except Exception as exc:
            raise AipacsWebError(
                f"Google sign-in was cancelled or did not complete: {exc}"
            )

        id_token = getattr(creds, "id_token", None)
        if not id_token:
            raise AipacsWebError(
                "Google sign-in did not return an ID token — try again."
            )
        payload = _decode_id_token_payload(id_token)
        email = str(payload.get("email") or "").strip()
        subject = str(payload.get("sub") or "").strip()
        if not email:
            raise AipacsWebError("Google did not report the account email.")
        if entered and email.lower() != entered.lower():
            raise AipacsWebError(
                f"You signed in as {email}, but entered {entered} — "
                "use the matching Google account."
            )
        return {"id_token": str(id_token), "subject": subject, "email": email}
    finally:
        # Transient attestation: drop the OAuth credentials. NEVER persist them
        # (no save_secret) — the only standing Google identity stays the hub
        # Drive account (ADR-0004).
        creds = None  # noqa: F841 - explicit discard


def link_google(
    base_url: str,
    *,
    gmail: str,
    id_token: str,
    workstation_user_id: str,
    server_id: str = "",
    center_id: str = "",
    device_name: str = "",
    session=None,
    timeout: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """``POST /auth/workstation/link-google`` → ``{"token", "user", "link", "profile"}``.

    The Laravel backend verifies the Google ID token and links the Gmail to an
    admin-defined consultation profile; 422 carries a clean message (e.g.
    "Your email is not registered for the Consultation module…"). BLOCKING
    network call — callers must run it off the Qt GUI thread.
    """
    from modules.Identity.thread_guard import assert_off_gui_thread

    assert_off_gui_thread("aipacs_web link-google")

    payload: dict[str, Any] = {
        "gmail": str(gmail or "").strip(),
        "id_token": str(id_token or ""),
        "workstation_user_id": str(workstation_user_id or ""),
        "device_name": device_name or default_device_name(),
    }
    if server_id:
        payload["server_id"] = str(server_id)
    if center_id:
        payload["center_id"] = str(center_id)

    if session is None:
        import requests

        session = requests.Session()
    url = f"{base_url.rstrip('/')}{API_PREFIX}/auth/workstation/link-google"
    try:
        # Accept header is REQUIRED (see pair_workstation note): otherwise a
        # Laravel ValidationException becomes a 302→HTML page and the real
        # error message is lost.
        resp = session.post(
            url, json=payload, timeout=timeout,
            headers={"Accept": "application/json"},
        )
    except Exception as exc:
        raise AipacsWebError(f"Could not reach the consultation server: {exc}")
    # 201 Created on success (200 kept for tolerance, like the pair endpoint).
    if getattr(resp, "status_code", 0) not in (200, 201):
        raise AipacsWebError(_extract_error(resp))
    try:
        data = resp.json()
    except Exception:
        raise AipacsWebError("Unexpected response from the consultation server.")
    if not isinstance(data, dict) or not data.get("token"):
        raise AipacsWebError("Linking did not return an access token.")
    return data


# ── API client ─────────────────────────────────────────────────────────────────
class AipacsWebClient:
    """Thin JSON client over the consult-form Sanctum API.

    Every call is a BLOCKING network round-trip and is therefore guarded off
    the Qt GUI thread (same rule as Google OAuth/Drive — see
    :mod:`modules.Identity.thread_guard`). Raises :class:`AipacsWebError` with
    a clean message on any failure.
    """

    def __init__(self, base_url: str, token: str, *, session=None,
                 timeout: int = DEFAULT_TIMEOUT_SEC):
        self.base_url = (base_url or "").rstrip("/")
        self._token = token or ""
        self._timeout = timeout
        self._session = session

    # -- plumbing ---------------------------------------------------------------
    def _ensure_session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def _request(self, method: str, path: str, *, json_body: dict | None = None,
                 params: dict | None = None, data=None, files=None,
                 timeout: int | None = None) -> Any:
        from modules.Identity.thread_guard import assert_off_gui_thread

        assert_off_gui_thread(f"aipacs_web {method} {path}")

        session = self._ensure_session()
        url = f"{self.base_url}{API_PREFIX}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        # A multipart body and a JSON body are mutually exclusive: a request
        # carrying both would send the JSON and silently drop the files.
        # ``Content-Type`` is left to requests, which has to generate the
        # multipart boundary itself.
        #
        # ``data``/``files`` are added to the call ONLY when there is something
        # to send, so a JSON request is passed exactly the arguments it always
        # was — the multipart feature cannot change the shape of a call that
        # does not use it.
        extra: dict[str, Any] = {}
        if files is not None:
            extra["files"] = files
        if data is not None:
            extra["data"] = data

        try:
            resp = session.request(
                method, url,
                json=None if files is not None else json_body,
                params=params, headers=headers,
                timeout=timeout or self._timeout,
                **extra,
            )
        except Exception as exc:
            # No status: the request never reached a response.
            raise AipacsWebError(f"Could not reach the consultation server: {exc}")
        status = getattr(resp, "status_code", 0)
        if status == 401:
            raise AipacsWebError(
                "Your AI-PACS Consultation session expired — sign in again.",
                status_code=401,
            )
        if status not in (200, 201):
            raise AipacsWebError(_extract_error(resp), status_code=status or None)
        try:
            return resp.json()
        except Exception:
            raise AipacsWebError(
                "Unexpected response from the consultation server.", status_code=status
            )

    def request_json(self, method: str, path: str, *, json_body: dict | None = None,
                     params=None, data=None, files=None,
                     timeout: int | None = None) -> Any:
        """The same request path, for modules that add their own endpoints.

        A public door onto ``_request`` so a module like AiPacs Chat can call
        ``/chat/*`` without either reaching into a private method or building a
        second client — which would mean a second copy of the bearer header,
        the thread guard, the 401 handling and the error extraction, and one of
        the copies would drift.

        ``params`` accepts a list of (key, value) PAIRS as well as a dict,
        because the chat filters post repeated keys (``attn[]`` twice) and a
        dict cannot hold those.

        ``data``/``files`` send a multipart body instead of JSON — chat
        attachments, which Laravel reads with ``$request->file('files.0')``.
        ``timeout`` overrides the client default for those: the JSON default is
        sized for a poll, and a 20 MB upload on a clinic's ADSL line is not.
        """
        return self._request(
            method, path, json_body=json_body, params=params,
            data=data, files=files, timeout=timeout,
        )

    @staticmethod
    def _rows(data: Any) -> list[dict]:
        """Unwrap a bare list or a Laravel envelope.

        The local backend wraps under resource-named keys
        (``{"consultants": [...]}``, ``{"consultations": [...]}``) — caught by
        the 2026-06-10 integration test; ``data`` kept for API-resource style.
        """
        if isinstance(data, dict):
            for key in ("data", "consultants", "consultations", "rows", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    return list(value)
            return []
        return list(data) if isinstance(data, list) else []

    # -- API methods ------------------------------------------------------------
    def me(self) -> dict:
        data = self._request("GET", "/me")
        return data.get("data", data) if isinstance(data, dict) else {}

    def consultants(self, type: str | None = None, specialty: str | None = None,
                    search: str | None = None) -> list[dict]:
        """``GET /consultants`` — optionally filtered (ADR-0007 A).

        ``type``/``specialty`` are passed to the server (it filters);
        ``search`` is matched client-side against name / specialty /
        expertise / interests (the backend has no search param in the v1
        contract). No arguments → byte-identical to the pre-ADR-0007 call.
        """
        params: dict[str, str] = {}
        if type:
            params["type"] = str(type).strip().lower()
        if specialty:
            params["specialty"] = str(specialty).strip()
        rows = self._rows(
            self._request("GET", "/consultants", params=params or None)
        )
        q = str(search or "").strip().lower()
        if q:
            def _hay(c: dict) -> str:
                return " ".join(
                    str(c.get(k) or "")
                    for k in ("name", "full_name", "specialty", "speciality",
                              "expertise", "consultation_interests")
                ).lower()

            rows = [c for c in rows if isinstance(c, dict) and q in _hay(c)]
        return rows

    def create_consultation(
        self,
        *,
        type: str,
        consultant_address: str,
        patient_ref: str,
        study_uid: str = "",
        note: str = "",
        drive_folder_id: str = "",
        center_id: str = "",
        patient_id: str = "",
        study_date: str = "",
        modality: str = "",
    ) -> dict:
        """``POST /consultations``.

        ``center_id`` / ``patient_id`` / ``study_date`` / ``modality`` are the
        OPTIONAL creation-only metadata fields (backend extension, 2026-06-12)
        — sent only when non-empty so the pre-v2 payload stays byte-identical.
        """
        body: dict[str, Any] = {
            "type": type,
            "consultant_address": consultant_address,
            "patient_ref": patient_ref,
        }
        if study_uid:
            body["study_uid"] = study_uid
        if note:
            body["note"] = note
        if drive_folder_id:
            body["drive_folder_id"] = drive_folder_id
        if center_id:
            body["center_id"] = str(center_id)
        if patient_id:
            body["patient_id"] = str(patient_id)
        if study_date:
            body["study_date"] = str(study_date)
        if modality:
            body["modality"] = str(modality)
        data = self._request("POST", "/consultations", json_body=body)
        return self._row(data)

    def list_consultations(self, box: str = "sent") -> list[dict]:
        return self._rows(
            self._request("GET", "/consultations", params={"box": box})
        )

    def update_consultation(self, consultation_id, **fields) -> dict:
        data = self._request(
            "PATCH", f"/consultations/{consultation_id}", json_body=dict(fields)
        )
        return self._row(data)

    @staticmethod
    def _row(data: Any) -> dict:
        """Unwrap a single-object envelope (``data``/``consultation``/``profile``/``storage``)."""
        if isinstance(data, dict):
            for key in ("data", "consultation", "profile", "storage"):
                value = data.get(key)
                if isinstance(value, dict):
                    return value
            return data
        return {}

    # -- profile / storage / shared (ADR-0007) -----------------------------------
    def my_profile(self) -> dict:
        """``GET /me/profile`` → ``{"profile": dict|None, "configured": bool}``.

        The envelope is meaningful here (``profile`` may legitimately be null
        for a not-yet-configured consultant), so it is preserved — only an
        outer ``data`` wrapper is stripped.
        """
        data = self._request("GET", "/me/profile")
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        if not isinstance(data, dict):
            return {"profile": None, "configured": False}
        profile = data.get("profile")
        if not isinstance(profile, dict):
            profile = None
        return {
            "profile": dict(profile) if profile else None,
            "configured": bool(data.get("configured", profile is not None)),
        }

    def update_my_profile(self, **fields) -> dict:
        """``PUT /me/profile`` with the self-managed fields (ADR-0007 B).

        ``address``/``type`` are server-controlled and are never sent.
        """
        body = {k: v for k, v in dict(fields).items() if k not in ("address", "type")}
        data = self._request("PUT", "/me/profile", json_body=body)
        return self._row(data)

    def my_storage(self) -> dict:
        """``GET /me/storage`` → quota/usage snapshot (Laravel authoritative)."""
        return self._row(self._request("GET", "/me/storage"))

    def storage_breakdown(self) -> dict:
        """``GET /me/storage/breakdown`` → totals + per-category + cleanup candidates.

        The breakdown body itself carries a ``breakdown`` sub-key, so only a
        true envelope (no marker keys at the top level) is unwrapped.
        """
        data = self._request("GET", "/me/storage/breakdown")
        if not isinstance(data, dict):
            return {}
        markers = ("total_bytes", "largest_folders", "cleanup_candidates")
        if any(k in data for k in markers):
            return data
        inner = data.get("data")
        if isinstance(inner, dict):
            return inner
        inner = data.get("breakdown")
        if isinstance(inner, dict) and any(k in inner for k in markers):
            return inner
        return data

    def shared_content(self) -> dict:
        """``GET /education/shared`` → ``{"shared_by_me": [...], "shared_with_me": [...]}``."""
        data = self._request("GET", "/education/shared")
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        if not isinstance(data, dict):
            data = {}
        return {
            "shared_by_me": [r for r in (data.get("shared_by_me") or [])
                             if isinstance(r, dict)],
            "shared_with_me": [r for r in (data.get("shared_with_me") or [])
                               if isinstance(r, dict)],
        }


# ── provider ───────────────────────────────────────────────────────────────────
class AipacsWebIdentityProvider(IdentityProvider):
    id = "aipacs_web"
    display_name = "AI-PACS Consultation"
    capabilities = {Capability.PROFILE, Capability.CONSULTATION}

    def is_available(self) -> tuple[bool, str]:
        try:
            import requests  # noqa: F401
        except Exception as exc:  # pragma: no cover - environment dependent
            return False, f"The 'requests' library is not installed: {exc}"
        if not aipacs_web_configured():
            return False, (
                "AI-PACS web backend not configured. Add "
                f"{AIPACS_WEB_CONFIG_FILE} with a base_url at: "
                f"{aipacs_web_config_path()}"
            )
        return True, "Ready to sign in."

    def connect(self, aipacs_user: str, credentials: dict | None = None) -> ExternalIdentity:
        """Pair with the web backend. BLOCKING — run off the GUI thread.

        ``credentials``: ``{"email": ..., "password": ...}`` or
        ``{"pairing_code": ...}`` (collected by the sign-in dialog; never stored).
        """
        ok, reason = self.is_available()
        if not ok:
            raise RuntimeError(reason)
        if not credentials:
            raise RuntimeError(
                "AI-PACS Consultation sign-in needs credentials "
                "(email+password or a pairing code)."
            )

        cfg = load_aipacs_web_config()
        base_url = cfg["base_url"]
        data = pair_workstation(base_url, credentials)
        user = data.get("user") or {}
        email = str(user.get("email") or credentials.get("email") or "").strip()
        subject = str(user.get("id") or email or "").strip()
        if not subject:
            raise AipacsWebError("Pairing did not return a stable account id.")

        identity = ExternalIdentity(
            provider=self.id,
            subject_id=subject,
            handle=email,
            display_name=str(user.get("name") or email or ""),
            capabilities=[c.value for c in self.capabilities],
            aipacs_user=aipacs_user,
            extra={"base_url": base_url},
        )

        from modules.Identity.secure_store import save_secret

        if not save_secret(self.id, subject, {"token": data["token"], "base_url": base_url}):
            logger.warning("aipacs_web token could not be stored securely for %s", subject)
        return identity

    def connect_via_google_attestation(
        self,
        aipacs_user: str,
        gmail: str = "",
        *,
        server_id: str = "",
        center_id: str = "",
    ) -> ExternalIdentity:
        """ADR-0008: link via transient Gmail attestation. BLOCKING (worker only).

        Runs :func:`attest_gmail` (openid+email ONLY, credentials discarded)
        then :func:`link_google`; the returned Sanctum token is stored EXACTLY
        like :meth:`connect` (same secure_store payload + identity shape).
        ``extra["link"]`` carries the link/profile snapshot so the UI can show
        "Linked: <gmail> (Dr. X)". No Google identity is ever written.

        ``gmail`` is OPTIONAL (unified one-step login): when empty the link is
        made with the Google-verified (attested) email.
        """
        ok, reason = self.is_available()
        if not ok:
            raise RuntimeError(reason)

        cfg = load_aipacs_web_config()
        base_url = cfg["base_url"]

        attestation = attest_gmail(gmail)
        data = link_google(
            base_url,
            gmail=attestation["email"],
            id_token=attestation["id_token"],
            workstation_user_id=aipacs_user,
            server_id=server_id,
            center_id=center_id,
        )

        user = data.get("user") or {}
        link = data.get("link") if isinstance(data.get("link"), dict) else {}
        profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
        email = str(user.get("email") or attestation["email"] or "").strip()
        subject = str(user.get("id") or email or "").strip()
        if not subject:
            raise AipacsWebError("Linking did not return a stable account id.")

        link_info: dict[str, Any] = dict(link)
        link_info.setdefault("gmail_email", attestation["email"])
        profile_name = str(
            (profile or {}).get("name") or user.get("name") or ""
        ).strip()
        if profile_name:
            link_info.setdefault("profile_name", profile_name)

        identity = ExternalIdentity(
            provider=self.id,
            subject_id=subject,
            handle=email,
            display_name=str(user.get("name") or profile_name or email or ""),
            capabilities=[c.value for c in self.capabilities],
            aipacs_user=aipacs_user,
            extra={"base_url": base_url, "link": link_info},
        )

        from modules.Identity.secure_store import save_secret

        if not save_secret(self.id, subject, {"token": data["token"], "base_url": base_url}):
            logger.warning("aipacs_web token could not be stored securely for %s", subject)
        return identity

    def disconnect(self, identity: ExternalIdentity) -> None:
        # No remote revoke endpoint in the v1 contract — removing the stored
        # token unpairs this workstation (the Laravel side can revoke tokens
        # from its own UI).
        from modules.Identity.secure_store import delete_secret

        delete_secret(self.id, identity.subject_id)

    def build_client(self, identity: ExternalIdentity) -> AipacsWebClient:
        """Build an authenticated API client from the stored token."""
        from modules.Identity.secure_store import load_secret

        payload = load_secret(self.id, identity.subject_id)
        if not payload or not payload.get("token"):
            raise AipacsWebError(
                "No stored AI-PACS Consultation token; sign in again."
            )
        base_url = (
            payload.get("base_url")
            or (identity.extra or {}).get("base_url")
            or load_aipacs_web_config().get("base_url")
            or ""
        )
        if not base_url:
            raise AipacsWebError("AI-PACS web backend base URL is not configured.")
        return AipacsWebClient(base_url, payload["token"])

    def get_capability_client(self, identity: ExternalIdentity, cap: Capability):
        if cap == Capability.CONSULTATION:
            return self.build_client(identity)
        return super().get_capability_client(identity, cap)


# ── convenience for consumers (education / account UI) ────────────────────────
def find_aipacs_web_identity(aipacs_user: str) -> ExternalIdentity | None:
    """Return the linked aipacs_web identity for this user, or None. Never raises."""
    try:
        from database import identity_db

        for ident in identity_db.list_identities(aipacs_user):
            if ident.provider == AipacsWebIdentityProvider.id:
                return ident
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("aipacs_web identity lookup failed: %s", exc)
    return None


def get_aipacs_web_client(aipacs_user: str) -> AipacsWebClient | None:
    """Authenticated client for the linked identity, or None when not signed in.

    Raises :class:`AipacsWebError` only for a *broken* link (token lost) — a
    plain "not signed in" state returns None so UIs can show a friendly prompt.
    """
    ident = find_aipacs_web_identity(aipacs_user)
    if ident is None:
        return None
    provider = AipacsWebIdentityProvider()
    return provider.build_client(ident)
