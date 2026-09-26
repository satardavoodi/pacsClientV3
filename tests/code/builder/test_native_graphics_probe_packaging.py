"""Both frozen workstation backends must preserve the early graphics child route."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
PROBE_MODULE = "modules.viewer.native_graphics_probe"
PROBE_VTK_MODULES = (
    "vtkmodules.vtkRenderingOpenGL2",
    "vtkmodules.vtkInteractionImage",
    "vtkmodules.vtkCommonDataModel",
    "vtkmodules.vtkCommonCore",
)


def test_pyinstaller_spec_pins_native_graphics_probe_and_vtk_inputs():
    spec = (ROOT / "builder/spec/appA_workstation.spec").read_text(encoding="utf-8")
    for module in (PROBE_MODULE, *PROBE_VTK_MODULES):
        assert f'"{module}"' in spec


def test_nuitka_full_core_pins_native_graphics_probe_and_vtk_inputs(monkeypatch):
    name = "native_probe_packaging_nuitka"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "builder nuitka/build_nuitka_release.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "existing_modules", lambda names: set(names))
    context = SimpleNamespace(version="3.6.7", spec=SimpleNamespace(),
                              args=SimpleNamespace(compiler="msvc"))
    command, _, _ = module.create_nuitka_command(
        context, module.STAGES[6], profile="full_core", entrypoint="main.py"
    )
    for name in (PROBE_MODULE, *PROBE_VTK_MODULES):
        assert "--include-module=" + name in command
