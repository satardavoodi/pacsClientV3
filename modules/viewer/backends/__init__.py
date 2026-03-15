from __future__ import annotations

import importlib


_EXPORTS = {
    "FrameData": "modules.viewer.fast.contracts",
    "GeometryData": "modules.viewer.fast.contracts",
    "IViewer2DBackend": "modules.viewer.fast.contracts",
    "PyDicom2DBackend": "modules.viewer.fast.pydicom_2d_backend",
    "PyDicomLazyVolume": "modules.viewer.fast.pydicom_lazy_volume",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
