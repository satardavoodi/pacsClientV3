"""Web Browser module package.

Lazy export (2026-06-27): ``WebBrowserWidget`` is imported on first access
via PEP 562 ``__getattr__`` instead of at package import time. Importing
``modules.web_browser`` (or its lightweight ``prewarm`` submodule) therefore
NO LONGER pulls in the heavy QtWebEngine DLLs — those load only when the
widget is actually constructed. This keeps app/home startup cheap and lets
the adaptive pre-warm (``prewarm.py``) schedule the Chromium boot at idle
instead of on the first user click. ``from modules.web_browser import
WebBrowserWidget`` and ``getattr(module, "WebBrowserWidget")`` both keep
working unchanged.
"""
from __future__ import annotations

__all__ = ["WebBrowserWidget"]


def __getattr__(name):  # PEP 562 lazy attribute access
    if name == "WebBrowserWidget":
        from .widget import WebBrowserWidget
        return WebBrowserWidget
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
