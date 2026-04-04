"""Shared utilities for HomePanelWidget and its services.

This module provides small, reusable helpers that eliminate duplicated
patterns across the home UI layer (e.g. widget-validity checking).

v2.2.8 architecture refactor.
"""
from __future__ import annotations


def is_widget_alive(widget) -> bool:
    """Return True if *widget* is a valid, non-deleted Qt object.

    Handles both the ``sip`` and the ``shiboken`` (PySide6) backends,
    and falls back to a property-access probe when neither is available.
    """
    if widget is None:
        return False
    # Fast path: sip (PyQt5/6)
    try:
        import sip
        return not sip.isdeleted(widget)
    except ImportError:
        pass
    # Fast path: shiboken (PySide6)
    try:
        import shiboken6
        return shiboken6.isValid(widget)
    except ImportError:
        pass
    # Fallback: attempt a property access
    try:
        _ = widget.isVisible()
        return True
    except RuntimeError:
        return False
