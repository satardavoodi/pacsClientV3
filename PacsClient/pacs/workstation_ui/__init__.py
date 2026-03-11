import importlib as _importlib

_MAP = {
    "MainWindowWidget": ".mainwindow_ui",
    "ControlPanelInterface": ".AIPacs_ui",
}

def __getattr__(name: str):
    if name in _MAP:
        mod = _importlib.import_module(_MAP[name], __name__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")