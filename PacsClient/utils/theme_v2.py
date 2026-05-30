"""Parallel V2 application-stylesheet builder (AI-PACS design migration).

**Phase 1 scaffold:** this currently MIRRORS V1 exactly by delegating to the
existing :meth:`ThemeManager.build_application_stylesheet`, so enabling
``ui_variant = "v2"`` produces **no visual change yet**. The real V2 QSS — built
from ``docs/design/IMPLEMENTATION_REFERENCE.md`` using the same theme token dict
— is filled in here incrementally, module by module, behind per-module gates.

It always consumes the token dict produced by
``theme_manager._theme_blueprint`` (passed via ``theme_manager``/``theme``), so
it never hard-codes color values (the no-hard-coded-hex invariant).
"""
from __future__ import annotations


def build_application_stylesheet_v2(theme_manager, theme=None) -> str:
    """Return the V2 application stylesheet.

    Phase 1: identical to V1. As each phase lands, the relevant QSS blocks are
    overridden here using ``theme`` token keys (e.g. ``{accent_hover}``), never
    literal hex.
    """
    return theme_manager.build_application_stylesheet(theme)
