import importlib as _importlib

_MAP = {
    "PatientWidget": ".patient_widget",
    "PatientTabWidget": ".patient_tab_widget",
    "CustomTabManager": ".custom_tab_manager",
}

__all__ = ['PatientWidget', 'PatientTabWidget', 'CustomTabManager']

def __getattr__(name: str):
    if name in _MAP:
        mod = _importlib.import_module(_MAP[name], __name__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
