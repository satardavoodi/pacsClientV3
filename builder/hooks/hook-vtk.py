"""Custom PyInstaller hook for vtk wrapper package."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_helper_module():
    helper_path = Path(__file__).resolve().with_name("_hook_helpers.py")
    spec = importlib.util.spec_from_file_location("aipacs_pyinstaller_hook_helpers", helper_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load hook helpers from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vtk_hook_payload = _load_helper_module().vtk_hook_payload

hiddenimports, datas, binaries = vtk_hook_payload()

