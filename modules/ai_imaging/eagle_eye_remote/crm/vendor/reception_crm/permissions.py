from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _candidate_roles_paths() -> tuple[Path, ...]:
    """Where to look for the roles policy, most specific first.

    Evaluated per call rather than at import time because a Windows service
    runs with ``C:\\Windows\\System32`` as its working directory: the relative
    entries below resolve against that and never match. ``config_root()`` is
    the installed, writable location and is what makes a packaged multi-center
    deployment work — the hardcoded ``D:\\RAZI crm`` entry only ever matched
    this one center.
    """
    from .runtime import config_root

    return (
        config_root() / "roles.json",
        Path("config/roles.json"),
        Path(r"D:\RAZI crm\config\roles.json"),
        config_root() / "roles.example.json",
        Path("config/roles.example.json"),
    )


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: str
    user: str | None
    center: str | None
    roles: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "user": self.user,
            "center": self.center,
            "roles": self.roles,
        }


class PermissionPolicy:
    def __init__(self, raw: dict[str, Any], path: Path):
        self.raw = raw
        self.path = path
        self.roles = dict(raw.get("roles", {}))
        self.users = dict(raw.get("users", {}))

    def check(self, user: str | None, center: str | None, operation: str, action: str, safety: str) -> PermissionDecision:
        if action == "read":
            return self._check_user_action(user, center, operation, "can_read", default_allow=False)
        if action == "plan":
            return self._check_user_action(user, center, operation, "can_plan", default_allow=False)
        if action == "execute":
            decision = self._check_user_action(user, center, operation, "can_execute", default_allow=False)
            if not decision.allowed:
                return decision
            if safety == "destructive" and not self._any_role_allows(user, "can_execute_destructive"):
                return PermissionDecision(False, "destructive operations are blocked for this user", user, center, decision.roles)
            return decision
        return PermissionDecision(False, f"unknown permission action: {action}", user, center, [])

    def _check_user_action(
        self,
        user: str | None,
        center: str | None,
        operation: str,
        capability: str,
        default_allow: bool,
    ) -> PermissionDecision:
        if not user:
            return PermissionDecision(default_allow, "anonymous default policy", user, center, [])

        user_record = self.users.get(user)
        if not user_record:
            return PermissionDecision(default_allow, "user not found; default policy applied", user, center, [])

        allowed_center = user_record.get("center")
        if allowed_center and center and allowed_center != center:
            return PermissionDecision(False, "user is not allowed for this center", user, center, list(user_record.get("roles", [])))

        user_roles = list(user_record.get("roles", []))
        for role_name in user_roles:
            role = self.roles.get(role_name, {})
            allowed_ops = list(role.get(capability, []))
            if "*" in allowed_ops or operation in allowed_ops:
                return PermissionDecision(True, f"allowed by role {role_name}", user, center, user_roles)
        return PermissionDecision(False, f"no role grants {capability} for {operation}", user, center, user_roles)

    def _any_role_allows(self, user: str | None, capability: str) -> bool:
        if not user:
            return False
        user_record = self.users.get(user) or {}
        for role_name in user_record.get("roles", []):
            role = self.roles.get(role_name, {})
            if bool(role.get(capability)):
                return True
        return False


def discover_roles_path(explicit_path: str | None = None) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        if not path.exists():
            raise FileNotFoundError(f"Roles policy was not found: {path}")
        return path
    for path in _candidate_roles_paths():
        if path.exists():
            return path
    raise FileNotFoundError("No roles policy found.")


def load_permissions(explicit_path: str | None = None) -> PermissionPolicy:
    path = discover_roles_path(explicit_path)
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return PermissionPolicy(raw, path)
