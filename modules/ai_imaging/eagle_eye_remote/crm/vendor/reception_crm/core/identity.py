"""Sessions and principals.

    A Principal is derived from an authenticated session.
    It is NEVER read from tool inputs.   (docs/security-model.md §2)

Login proves *who you are* against the CRM itself: we attempt a real CRM login
with the credentials the user typed. If the CRM accepts them, the user exists.
What you are *allowed to do* then comes from the local role policy
(``config/roles.json``) — the CRM proves identity, Reception CRM assigns authority.

The session token is a signed, self-contained bearer (HMAC-SHA256 over a JSON
payload). It carries no secret: it *names* a user, and the signature proves the
server minted it. A model cannot forge one, because a model does not have the
signing secret — and, crucially, cannot obtain one by typing a username.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass

from ..permissions import load_permissions
from ..settings import resolve_center
from .errors import ReceptionCoreError
from .types import Principal

DEFAULT_TTL_SECONDS = 8 * 60 * 60  # 8 hours, matching the CRM's own token life
_SECRET_ENV = "RECEPTION_SESSION_SECRET"

# Process-lifetime revocation list (logout). A restart clears it — acceptable
# while sessions are short-lived; move to the storage layer if that changes.
_REVOKED: set[str] = set()

# Generated per process when no secret is configured: every restart then
# invalidates outstanding sessions, which is safe (fail-closed) but noisy.
_EPHEMERAL_SECRET = secrets.token_hex(32)


class AuthError(ReceptionCoreError):
    code = "UNAUTHORIZED"


class SessionExpiredError(ReceptionCoreError):
    code = "AUTH_EXPIRED"


@dataclass(frozen=True)
class Session:
    token: str
    principal: Principal
    session_id: str
    expires_at: int
    display_name: str = ""


def _secret() -> bytes:
    return (os.environ.get(_SECRET_ENV) or _EPHEMERAL_SECRET).encode("utf-8")


def roles_for(user: str, center: str | None) -> list[str]:
    """Roles from the local policy. An unknown user gets NO roles (default deny)."""
    try:
        policy = load_permissions()
    except FileNotFoundError:
        return []
    record = policy.users.get(user) or {}
    allowed_center = record.get("center")
    if allowed_center and center and allowed_center != center:
        return []
    return list(record.get("roles", []))


def login(username: str, password: str, center: str | None = None, device_id: str = "") -> Session:
    """Validate credentials against the CRM, then mint a session.

    The password is used once, here, and never stored, logged, or audited.
    """
    username = str(username or "").strip()
    if not username or not password:
        raise AuthError("Username and password are required.")

    from ..ino_api import InoApiError, InoClient

    client = InoClient.from_env()
    client.username = username
    client.password = password
    client.token = None
    try:
        client.login()
    except InoApiError as exc:
        # Never echo the upstream body: it can contain the submitted credential.
        raise AuthError("Login failed. Check the username and password.") from exc

    resolved_center = resolve_center(center)
    roles = roles_for(username, resolved_center)
    if not roles:
        # Authenticated, but nobody has granted this user anything. That is an
        # authorization gap, not a low-privilege user — say so instead of
        # silently handing out a default role.
        raise AuthError(f"User '{username}' has no role in config/roles.json for center {resolved_center}.")

    # auth_method is what the audit log uses to say HOW someone got in. Leaving
    # it at the default "unknown" here made a real per-user login indistinguishable
    # from an unattributed one, while the shared-token path correctly reported
    # "shared_token".
    return issue(
        Principal(user=username, center=resolved_center, roles=roles, auth_method="session"),
        device_id=device_id,
    )


def issue(principal: Principal, device_id: str = "", ttl: int = DEFAULT_TTL_SECONDS) -> Session:
    session_id = f"ses_{uuid.uuid4().hex[:16]}"
    expires_at = int(time.time()) + int(ttl)
    payload = {
        "sid": session_id,
        "user": principal.user,
        "center": principal.center,
        "roles": list(principal.roles),
        "device": device_id,
        "exp": expires_at,
    }
    raw = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signature = _b64(hmac.new(_secret(), raw.encode("ascii"), hashlib.sha256).digest())
    return Session(
        token=f"{raw}.{signature}",
        principal=principal,
        session_id=session_id,
        expires_at=expires_at,
    )


def resolve(token: str) -> Principal:
    """Token → Principal. Raises rather than returning an anonymous principal."""
    parts = str(token or "").split(".")
    if len(parts) != 2:
        raise AuthError("Malformed session token.")
    raw, signature = parts
    expected = _b64(hmac.new(_secret(), raw.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        raise AuthError("Invalid session token.")

    try:
        payload = json.loads(_unb64(raw))
    except Exception as exc:  # noqa: BLE001
        raise AuthError("Malformed session token.") from exc

    if payload.get("sid") in _REVOKED:
        raise AuthError("This session has been revoked.")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise SessionExpiredError("Session expired. Please sign in again.")

    # A verified session token IS the proof of how this caller authenticated, so
    # say so. Without it every audited request made with a session token recorded
    # auth_method "unknown", which is exactly the question the audit log exists
    # to answer.
    return Principal(
        user=str(payload.get("user") or "") or None,
        center=str(payload.get("center") or "") or None,
        roles=list(payload.get("roles") or []),
        auth_method="session",
    )


def revoke(token: str) -> None:
    try:
        raw = str(token or "").split(".")[0]
        payload = json.loads(_unb64(raw))
    except Exception:  # noqa: BLE001 - a token we cannot read is already useless
        return
    sid = payload.get("sid")
    if sid:
        _REVOKED.add(str(sid))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
