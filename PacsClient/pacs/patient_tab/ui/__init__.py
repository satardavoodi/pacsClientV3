import importlib as _importlib

_MAP = {
    "PatientWidget": "PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget",
    "VTKWidget": "PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer",
}

def __getattr__(name: str):
    if name in _MAP:
        mod = _importlib.import_module(_MAP[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")