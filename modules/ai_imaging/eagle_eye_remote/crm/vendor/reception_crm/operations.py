from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOG = logging.getLogger("reception_crm.operations")


def _candidate_operations_paths() -> tuple[Path, ...]:
    """Operation registry locations, most specific first.

    Resolved per call for the same reason as the roles policy: a service's
    working directory is ``C:\\Windows\\System32``, so relative paths never
    match. See ``permissions._candidate_roles_paths``.
    """
    from .runtime import bundle_dir, config_root

    return (
        config_root() / "operations.json",
        Path("config/operations.json"),
        Path(r"D:\RAZI crm\config\operations.json"),
        # Shipped inside the frozen bundle as a last-resort default.
        bundle_dir() / "config" / "operations.json",
    )

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)(?:\|([^}]+))?\s*\}\}")


class OperationError(RuntimeError):
    """Raised when an operation registry entry cannot be planned safely."""


@dataclass(frozen=True)
class OperationPlan:
    name: str
    method: str
    url: str
    safety: str
    enabled: bool
    missing_required_inputs: list[str]
    query: dict[str, Any]
    body: Any
    dry_run_only: bool
    confirmation_required: bool
    notes: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "method": self.method,
            "url": self.url,
            "safety": self.safety,
            "enabled": self.enabled,
            "missing_required_inputs": self.missing_required_inputs,
            "query": self.query,
            "body": self.body,
            "dry_run_only": self.dry_run_only,
            "confirmation_required": self.confirmation_required,
            "notes": self.notes,
        }


class OperationRegistry:
    def __init__(self, raw: dict[str, Any], path: Path):
        self.raw = raw
        self.path = path
        self.base_urls = dict(raw.get("base_urls", {}))
        self.defaults = dict(raw.get("defaults", {}))
        self.operations = list(raw.get("operations", []))

    def list_operations(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item["name"],
                "title": item.get("title", ""),
                "method": item.get("method", "GET"),
                "safety": item.get("safety", "read"),
                "enabled": bool(item.get("enabled", False)),
            }
            for item in self.operations
        ]

    def get(self, name: str) -> dict[str, Any]:
        for item in self.operations:
            if item.get("name") == name:
                return item
        raise OperationError(f"Unknown operation: {name}")

    def plan(self, name: str, inputs: dict[str, Any] | None = None) -> OperationPlan:
        inputs = inputs or {}
        operation = self.get(name)
        required = list(operation.get("inputs", {}).get("required", []))
        missing = [field for field in required if field not in inputs or inputs[field] in (None, "")]
        url = render_template(operation["url"], inputs, self.base_urls)
        query = render_object(operation.get("query_template", {}), inputs, self.base_urls)
        body_source = operation.get("body_template") or operation.get("body_template_observed_fields")
        body = prune_empty(render_object(body_source, inputs, self.base_urls)) if body_source is not None else None
        safety = operation.get("safety", "read")
        enabled = bool(operation.get("enabled", False))
        confirmation = dict(operation.get("confirmation", {}))
        dry_run_only = safety != "read" and (
            self.defaults.get("write_mode") == "dry_run_only"
            or not enabled
        )
        confirmation_required = bool(confirmation.get("required", safety != "read"))
        return OperationPlan(
            name=name,
            method=operation.get("method", "GET").upper(),
            url=url,
            safety=safety,
            enabled=enabled,
            missing_required_inputs=missing,
            query={key: value for key, value in query.items() if value is not None},
            body=body,
            dry_run_only=dry_run_only,
            confirmation_required=confirmation_required,
            notes=operation.get("notes"),
        )


def discover_operations_path(explicit_path: str | None = None) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        if not path.exists():
            raise FileNotFoundError(f"Operation registry was not found: {path}")
        return path
    for path in _candidate_operations_paths():
        if path.exists():
            return path
    raise FileNotFoundError("No operation registry found.")


def load_operations(explicit_path: str | None = None) -> OperationRegistry:
    path = discover_operations_path(explicit_path)
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    # The operator's saved profile decides which hosts these operations POST
    # to. `load_settings()` does not raise when there is no settings file — it
    # builds one from the environment — so everything caught here means the
    # file exists and could not be read, and the registry then keeps the base
    # URLs written in operations.json instead.
    #
    # This matters more here than anywhere else in the package: operations are
    # the WRITE actions. Swallowed, an unreadable settings file sends a booking
    # or a cancellation to whichever host the file happens to name, and the
    # only trace is that it worked.
    #
    # The fallback stays — refusing to load the registry would take the agent
    # down entirely — but it is no longer silent.
    try:
        from .settings import load_settings, settings_path
    except ImportError:  # pragma: no cover - settings is part of the package
        return OperationRegistry(raw, path)

    try:
        profile = load_settings().active()
    except Exception as exc:  # noqa: BLE001 - reported, then degraded deliberately
        LOG.error(
            "Could not read connection settings at %s (%s: %s). Operations will "
            "use the base URLs in %s, which may target a DIFFERENT centre than "
            "the one configured.",
            settings_path(), type(exc).__name__, exc, path,
        )
    else:
        raw["base_urls"] = {**raw.get("base_urls", {}), **profile.base_urls}
    return OperationRegistry(raw, path)


def render_object(value: Any, inputs: dict[str, Any], base_urls: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: render_object(child, inputs, base_urls) for key, child in value.items()}
    if isinstance(value, list):
        return [render_object(child, inputs, base_urls) for child in value]
    if isinstance(value, str):
        return render_template(value, inputs, base_urls)
    return value


def render_template(template: str, inputs: dict[str, Any], base_urls: dict[str, str]) -> str | Any:
    exact = PLACEHOLDER_RE.fullmatch(template)
    if exact:
        key = exact.group(1)
        default = exact.group(2)
        return lookup_value(key, inputs, base_urls, default)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        default = match.group(2)
        value = lookup_value(key, inputs, base_urls, default)
        return "" if value is None else str(value)

    return PLACEHOLDER_RE.sub(replace, template)


def lookup_value(
    key: str,
    inputs: dict[str, Any],
    base_urls: dict[str, str],
    default: str | None,
) -> Any:
    if key in base_urls:
        return base_urls[key]
    if key in inputs:
        return inputs[key]
    return parse_default(default)


def parse_default(default: str | None) -> Any:
    if default is None:
        return None
    if default in {"[]", "{}", "null", "true", "false"}:
        return json.loads(default)
    try:
        return int(default)
    except ValueError:
        pass
    try:
        return float(default)
    except ValueError:
        return default


def prune_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: prune_empty(child)
            for key, child in value.items()
            if child is not None
        }
    if isinstance(value, list):
        return [prune_empty(child) for child in value]
    return value
