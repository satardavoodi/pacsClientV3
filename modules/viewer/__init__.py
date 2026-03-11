"""Patient-tab viewers package.

Subpackages
-----------
- ``vtk``     – VTK / SimpleITK advance viewer (2-D, 3-D, presets, filters)
- ``pydicom`` – PyDicom fast viewer (lazy backend, Qt pipeline, registry)

Keep this module lightweight. Do not import heavy viewer modules at import time,
otherwise importing a submodule can trigger circular imports during bootstrap.
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
    "AIChatViewer": ("modules.EchoMind.viewer_chat.ai_chat_viewer", "AIChatViewer"),
    "ImageViewer2D": ("modules.viewer.advanced.viewer_2d", "ImageViewer2D"),
    "ImageReslice": ("modules.viewer.advanced.viewer_2d", "ImageReslice"),
    "ViewerType": ("modules.viewer.advanced.viewer_2d", "ViewerType"),
    "Viewer3DWidget": ("modules.viewer.advanced.viewer_3d", "Viewer3DWidget"),
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
