"""Typed structured-logging emit helpers (Phase 0.1, plan ARCHITECTURE_REVIEW_2026-04-30).

This module is the single sanctioned way to emit ``[TAG] key=value ...`` style
structured logs that the KPI harness parses. It replaces the
``logger.info(..., extra={"component": "download", ...})`` pattern that has
silently caused the same class of bug **three times** in production:

1. R13 ``[SP]`` subprocess priority logs (component=ipc was correct, but
   earlier copies used component=download → INFO dropped).
2. R19 ``[INTENT_PRIORITY]`` priority handoff logs (live pid=32956 produced
   zero hits because ``logger.info`` + ``component=download`` was silently
   dropped — download threshold is WARNING).
3. R22 ``[DM_REBUILD]`` / ``[DM_PRIORITY_TRANSITION]`` table-rebuild logs
   (same root cause).

The contract:

- ``component=download`` ⇒ minimum level WARNING
- ``component=ipc``      ⇒ minimum level INFO
- ``component=viewer``   ⇒ minimum level INFO
- ``component=zetaboost``⇒ minimum level INFO
- ``component=db``       ⇒ minimum level INFO
- ``component=ui``       ⇒ minimum level INFO

The helpers below set the correct ``component`` value AND select a level
guaranteed to be ≥ the component threshold. They also format the
``[TAG] key=value ...`` body deterministically so KPI parsers stay stable.

Direct ``logger.<level>(..., extra={"component": ...})`` calls are still
allowed for non-tagged free-form messages (most existing call sites), but
new ``[TAG]`` style emit sites should go through this module. A lint test
in ``tests/utils/test_structured_logging_lint.py`` flags any direct
emit that combines a level lower than the component threshold with a
``[TAG]`` style format string.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping, Optional

__all__ = [
    "emit_download_event",
    "emit_ipc_event",
    "emit_viewer_event",
    "emit_zetaboost_event",
    "emit_db_event",
    "emit_ui_event",
    "format_event_message",
    "MIN_LEVEL_BY_COMPONENT",
]


# Mirror of ``_DEFAULT_COMPONENT_THRESHOLDS`` in
# ``PacsClient/utils/diagnostic_logging.py``. Keep in sync.
MIN_LEVEL_BY_COMPONENT: Mapping[str, int] = {
    "viewer": logging.INFO,
    "download": logging.WARNING,
    "zetaboost": logging.INFO,
    "db": logging.INFO,
    "ipc": logging.INFO,
    "ui": logging.INFO,
    "other": logging.INFO,
}


# Field-value sanitization (matches slot_timing.py R21 contract):
#   ``;`` → ``,`` and ``=`` → ``:`` so the ``key=value;key2=value2`` body
# format is never broken by user-supplied values (e.g. file paths, exception
# strings, dict reprs).
_FIELD_SEP_REPLACEMENTS = (
    (";", ","),
    ("=", ":"),
    ("\n", " "),
    ("\r", " "),
)


def _sanitize_field_value(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        # Default float formatting to 3 decimals where reasonable. Callers
        # that need different precision should pre-format and pass a string.
        return f"{value:.3f}"
    s = str(value)
    for old, new in _FIELD_SEP_REPLACEMENTS:
        s = s.replace(old, new)
    return s


def format_event_message(tag: str, fields: Iterable[tuple[str, Any]]) -> str:
    """Build ``[TAG] k1=v1 k2=v2 ...`` from an iterable of (key, value)."""
    parts = [f"[{tag}]"]
    for key, value in fields:
        if value is None:
            continue
        parts.append(f"{key}={_sanitize_field_value(value)}")
    return " ".join(parts)


def _emit(
    logger: logging.Logger,
    *,
    component: str,
    tag: str,
    level: Optional[int],
    extra_fields: Optional[Mapping[str, Any]],
    fields: Mapping[str, Any],
) -> None:
    min_level = MIN_LEVEL_BY_COMPONENT.get(component, logging.INFO)
    if level is None or level < min_level:
        level = min_level

    message = format_event_message(tag, fields.items())

    extra: dict[str, Any] = {"component": component}
    if extra_fields:
        for key, value in extra_fields.items():
            if value is None:
                continue
            extra[key] = value

    logger.log(level, message, extra=extra)


def emit_download_event(
    logger: logging.Logger,
    tag: str,
    *,
    level: int = logging.WARNING,
    extra: Optional[Mapping[str, Any]] = None,
    **fields: Any,
) -> None:
    """Emit ``[TAG] k=v ...`` with ``component=download``.

    Default level is WARNING because the ``download`` component threshold
    is WARNING in ``diagnostic_logging.py`` — INFO would be silently
    dropped. Pass a higher level (ERROR/CRITICAL) explicitly when needed.
    """
    _emit(
        logger,
        component="download",
        tag=tag,
        level=level,
        extra_fields=extra,
        fields=fields,
    )


def emit_ipc_event(
    logger: logging.Logger,
    tag: str,
    *,
    level: int = logging.INFO,
    extra: Optional[Mapping[str, Any]] = None,
    **fields: Any,
) -> None:
    """Emit ``[TAG] k=v ...`` with ``component=ipc`` (subprocess / IPC)."""
    _emit(
        logger,
        component="ipc",
        tag=tag,
        level=level,
        extra_fields=extra,
        fields=fields,
    )


def emit_viewer_event(
    logger: logging.Logger,
    tag: str,
    *,
    level: int = logging.INFO,
    extra: Optional[Mapping[str, Any]] = None,
    **fields: Any,
) -> None:
    """Emit ``[TAG] k=v ...`` with ``component=viewer``."""
    _emit(
        logger,
        component="viewer",
        tag=tag,
        level=level,
        extra_fields=extra,
        fields=fields,
    )


def emit_zetaboost_event(
    logger: logging.Logger,
    tag: str,
    *,
    level: int = logging.INFO,
    extra: Optional[Mapping[str, Any]] = None,
    **fields: Any,
) -> None:
    """Emit ``[TAG] k=v ...`` with ``component=zetaboost``."""
    _emit(
        logger,
        component="zetaboost",
        tag=tag,
        level=level,
        extra_fields=extra,
        fields=fields,
    )


def emit_db_event(
    logger: logging.Logger,
    tag: str,
    *,
    level: int = logging.INFO,
    extra: Optional[Mapping[str, Any]] = None,
    **fields: Any,
) -> None:
    """Emit ``[TAG] k=v ...`` with ``component=db``."""
    _emit(
        logger,
        component="db",
        tag=tag,
        level=level,
        extra_fields=extra,
        fields=fields,
    )


def emit_ui_event(
    logger: logging.Logger,
    tag: str,
    *,
    level: int = logging.INFO,
    extra: Optional[Mapping[str, Any]] = None,
    **fields: Any,
) -> None:
    """Emit ``[TAG] k=v ...`` with ``component=ui``."""
    _emit(
        logger,
        component="ui",
        tag=tag,
        level=level,
        extra_fields=extra,
        fields=fields,
    )
