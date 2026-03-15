"""Compatibility shim for the Web Browser module."""

from importlib import import_module

__all__ = ["WebBrowserWidget"]


def __getattr__(name):
    if name != "WebBrowserWidget":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module("modules.web_browser")
    value = getattr(module, name)
    globals()[name] = value
    return value
