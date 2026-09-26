"""Bounded, crash-isolated admission check for the embedded Windows VTK viewer.

DLL presence and Qt's software GL context do not establish that VTK's Win32
context works. Run before QApplication, once per launch, never per viewer click.
Headless Eagle Eye service dispatch exits before this GUI bootstrap.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROBE_ARGUMENT = "--aipacs-native-graphics-probe"
RESULT_PREFIX = "AIPACS_NATIVE_GRAPHICS="
BLOCKED_ENV = "AIPACS_NATIVE_VTK_BLOCKED"


def native_vtk_blocked() -> bool:
    return os.environ.get(BLOCKED_ENV) == "1"


def _probe_child() -> bool:
    # Python 3.8+ does not use PATH for extension-module dependencies. Retain
    # the parent's explicitly selected graphics directories in the child too.
    handles = []
    for directory in json.loads(os.environ.get("AIPACS_GRAPHICS_PROBE_DLL_DIRS", "[]")):
        if hasattr(os, "add_dll_directory"):
            handles.append(os.add_dll_directory(directory))
    from vtkmodules.vtkRenderingOpenGL2 import vtkWin32OpenGLRenderWindow

    window = vtkWin32OpenGLRenderWindow()
    window.SetOffScreenRendering(1)
    supported = bool(window.SupportsOpenGL())
    if supported:
        # Exercise the exact native boundary that failed on Razi, with no
        # patient content. A native fault here kills only this child process.
        from vtkmodules.vtkCommonDataModel import vtkImageData
        from vtkmodules.vtkCommonCore import VTK_UNSIGNED_CHAR
        from vtkmodules.vtkInteractionImage import vtkResliceImageViewer

        image = vtkImageData()
        image.SetDimensions(8, 8, 2)
        image.AllocateScalars(VTK_UNSIGNED_CHAR, 1)
        image.GetPointData().GetScalars().Fill(0)
        viewer = vtkResliceImageViewer()
        viewer.SetRenderWindow(window)
        window.SetSize(32, 32)
        window.Initialize()
        viewer.SetInputData(image)
        viewer.Render()
        window.Finalize()
    return supported


def dispatch_probe(argv: list[str]) -> bool:
    """Internal source/frozen child route; must run before application startup."""
    if PROBE_ARGUMENT not in argv[1:]:
        return False
    try:
        supported = _probe_child()
    except Exception:
        supported = False
    payload = json.dumps({"supported": supported})
    receipt = os.environ.get("AIPACS_GRAPHICS_PROBE_RECEIPT")
    if receipt:
        Path(receipt).write_text(payload, encoding="utf-8")
    elif sys.stdout is not None:
        print(RESULT_PREFIX + payload, flush=True)
    return True


def probe_native_graphics(*, dll_directories=(), timeout: float = 15.0) -> dict:
    """A crash, timeout, missing runtime or malformed receipt fails closed."""
    root = Path(__file__).resolve().parents[2]
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command += [str(root / "main.py")]
    command += [PROBE_ARGUMENT]
    environment = os.environ.copy()
    environment["AIPACS_GRAPHICS_PROBE_DLL_DIRS"] = json.dumps(list(dll_directories))
    try:
        # Windowed PyInstaller/Nuitka executables may have no stdout at all.
        # A private per-launch receipt works for source and both packagers.
        with tempfile.TemporaryDirectory(prefix="aipacs-graphics-") as directory:
            receipt = Path(directory) / "result.json"
            environment["AIPACS_GRAPHICS_PROBE_RECEIPT"] = str(receipt)
            completed = subprocess.run(
                command, cwd=root, env=environment, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0:
                return {"supported": False, "reason": "probe_process_failed"}
            if not receipt.is_file() or receipt.stat().st_size > 1024:
                return {"supported": False, "reason": "invalid_probe_receipt"}
            payload = receipt.read_text(encoding="utf-8")
    except subprocess.TimeoutExpired:
        return {"supported": False, "reason": "probe_timeout"}
    except OSError:
        return {"supported": False, "reason": "probe_launch_failed"}
    try:
        supported = json.loads(payload).get("supported") is True
        return {"supported": supported,
                "reason": "verified" if supported else "native_opengl_unavailable"}
    except (ValueError, AttributeError):
        return {"supported": False, "reason": "invalid_probe_receipt"}


def apply_native_graphics_result(result: dict) -> None:
    """Keep the existing VTK-free viewer route authoritative on failure."""
    if result.get("supported") is True:
        os.environ.pop(BLOCKED_ENV, None)
    else:
        from aipacs_runtime import SAFE_VIEWER_BACKEND_ENV, SAFE_VIEWER_BACKEND_DEFAULT
        os.environ[BLOCKED_ENV] = "1"
        os.environ[SAFE_VIEWER_BACKEND_ENV] = SAFE_VIEWER_BACKEND_DEFAULT
