"""Shared helpers for FAST series identifier normalization.

These helpers intentionally stay small and conservative. They centralize the
common logic for resolving a caller-provided series identifier into the
canonical series-number string used by FAST viewer components, while allowing
callers to layer on their own local fallbacks.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def get_series_number(series_info: Mapping[str, Any] | None) -> str:
    """Return the normalized series-number string from a series-info mapping."""
    if not isinstance(series_info, Mapping):
        return ""
    value = series_info.get("series_number", "")
    return str(value or "").strip()


def get_series_uid(series_info: Mapping[str, Any] | None) -> str:
    """Return the best available series UID from a series-info mapping."""
    if not isinstance(series_info, Mapping):
        return ""
    value = series_info.get("series_uid") or series_info.get("series_instance_uid") or ""
    return str(value or "").strip()


def resolve_series_identifier(
    series_identifier: Any,
    *,
    known_series_numbers: Iterable[Any] | None = None,
    uid_to_number_map: Mapping[str, Any] | None = None,
    series_info_map: Mapping[Any, Mapping[str, Any]] | None = None,
) -> str:
    """Resolve a series identifier to the canonical series-number string.

    Resolution order is deliberately conservative and mirrors the existing FAST
    behavior used by thumbnails and DM progress wiring:

    1. Exact match against known series-number keys.
    2. Numeric identifier shortcut.
    3. Direct lookup in UID→series-number mapping.
    4. Scan of series-info mappings using series UID fields.
    5. Fallback to the original identifier string.
    """
    series_key = str(series_identifier or "").strip()
    if not series_key:
        return ""

    if known_series_numbers is not None:
        try:
            known_keys = {str(value) for value in known_series_numbers}
        except Exception:
            known_keys = set()
        if series_key in known_keys:
            return series_key

    if series_key.isdigit():
        return series_key

    if uid_to_number_map:
        try:
            mapped = uid_to_number_map.get(series_key)
        except Exception:
            mapped = None
        if mapped is not None and str(mapped).strip():
            return str(mapped).strip()

    if series_info_map:
        try:
            items = series_info_map.items()
        except Exception:
            items = ()
        for series_number, info in items:
            if get_series_uid(info) == series_key:
                return str(series_number).strip()

    return series_key