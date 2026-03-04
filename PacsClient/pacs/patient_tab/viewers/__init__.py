"""Patient-tab viewers package.

Keep this module lightweight. Do not import heavy viewer modules at import time,
otherwise importing a submodule like ``viewers.backends.*`` can trigger circular
imports during application bootstrap.
"""

from importlib import import_module

__all__ = [
    "AIChatViewer",
    "ImageViewer2D",
    "ImageReslice",
    "ViewerType",
    "Viewer3DWidget",
]

_EXPORTS = {
    "AIChatViewer": ("PacsClient.pacs.patient_tab.viewers.ai_chat_viewer", "AIChatViewer"),
    "ImageViewer2D": ("PacsClient.pacs.patient_tab.viewers.viewer_2d", "ImageViewer2D"),
    "ImageReslice": ("PacsClient.pacs.patient_tab.viewers.viewer_2d", "ImageReslice"),
    "ViewerType": ("PacsClient.pacs.patient_tab.viewers.viewer_2d", "ViewerType"),
    "Viewer3DWidget": ("PacsClient.pacs.patient_tab.viewers.viewer_3d", "Viewer3DWidget"),
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals().keys()) | set(__all__))
