"""Lazy public exports for Eagle Eye service tabs.

The active imaging tab imports directly. Secondary tabs remain import- and
construction-lazy until selected, which keeps their optional dependencies out
of the patient-open first-paint path while preserving legacy imports.
"""
from importlib import import_module


_EXPORTS = {
    "AIPatientWidget": (
        "modules.ai_imaging.ai_module_ui.overrides",
        "AIPatientWidget",
    ),
    "AbstractTab": (
        "modules.ai_imaging.ai_module_ui.service_tab.abstract_tab",
        "AbstractTab",
    ),
    "ImagingToolsTab": (
        "modules.ai_imaging.ai_module_ui.service_tab.imaging_tab",
        "ImagingToolsTab",
    ),
    "ModelTrainingTab": (
        "modules.ai_imaging.ai_module_ui.service_tab.model_tab",
        "ModelTrainingTab",
    ),
    "ReceptionDataTab": (
        "modules.ai_imaging.ai_module_ui.service_tab.reception_data_tab",
        "ReceptionDataTab",
    ),
    "DataSetTab": (
        "modules.ai_imaging.ai_module_ui.service_tab.dataset_tab",
        "DataSetTab",
    ),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
